#include "pulse_max30102.h"

#include <DFRobot_MAX30102.h>
#include <Wire.h>

#include "config.h"

static DFRobot_MAX30102 sensor;

bool PulseMonitor::begin() {
    Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);

    // Try a few times: the module can need a moment after power-up
    for (int attempt = 0; attempt < 3 && !present_; attempt++) {
        present_ = sensor.begin();
        if (!present_) delay(200);
    }
    if (!present_) return false;

    sensor.sensorConfiguration(
        PULSE_LED_BRIGHTNESS,
        SAMPLEAVG_4,     // average 4 samples
        MODE_MULTILED,   // red + IR, needed for SpO2
        SAMPLERATE_100,  // 100 samples/s
        PULSEWIDTH_411,  // 18-bit resolution
        ADCRANGE_16384);

    // Core 0, low priority: leaves core 1 free for the 50 Hz accelerometer loop
    xTaskCreatePinnedToCore(taskEntry, "pulse", 6144, this, 1, nullptr, 0);
    return true;
}

Vitals PulseMonitor::latest() {
    portENTER_CRITICAL(&mux_);
    Vitals copy = vitals_;
    portEXIT_CRITICAL(&mux_);
    return copy;
}

void PulseMonitor::publish(const Vitals& v) {
    portENTER_CRITICAL(&mux_);
    const uint32_t seq = vitals_.sequence + 1;
    vitals_ = v;
    vitals_.sequence = seq;
    portEXIT_CRITICAL(&mux_);
}

void PulseMonitor::taskEntry(void* arg) {
    static_cast<PulseMonitor*>(arg)->taskLoop();
}

void PulseMonitor::taskLoop() {
    for (;;) {
        Vitals v;
        v.updatedMs = millis();

        // Skip the 4 s measurement if the sensor isn't against the skin
        v.contact = sensor.getIR() > PULSE_CONTACT_IR;
        if (!v.contact) {
            hrCount_ = 0;
            publish(v);
            vTaskDelay(pdMS_TO_TICKS(1000));
            continue;
        }

        int32_t spo2 = 0, hr = 0;
        int8_t spo2Valid = 0, hrValid = 0;
        sensor.heartrateAndOxygenSaturation(&spo2, &spo2Valid, &hr, &hrValid);
        v.updatedMs = millis();

        // Drop physiologically impossible values (motion artifacts, poor contact)
        v.hrValid = hrValid && hr >= 35 && hr <= 220;
        v.spo2Valid = spo2Valid && spo2 >= 70 && spo2 <= 100;

        if (v.hrValid) {
            // Median of the last 3 good readings smooths single bad measurements
            hrHistory_[hrCount_ % 3] = (int16_t)hr;
            hrCount_++;
            if (hrCount_ >= 3) {
                int16_t a = hrHistory_[0], b = hrHistory_[1], c = hrHistory_[2];
                int16_t median = max(min(a, b), min(max(a, b), c));
                v.heartRate = median;
            } else {
                v.heartRate = (int16_t)hr;
            }
        }
        if (v.spo2Valid) v.spo2 = (int16_t)spo2;

        publish(v);
        vTaskDelay(pdMS_TO_TICKS(10));  // let the idle task run
    }
}
