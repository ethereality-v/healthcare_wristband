// GY-MAX30102 heart rate + SpO2, based on the team's pulse oximeter code (DFRobot_MAX30102 library).
//
// The library's measurement blocks for ~4 s while it collects 100 samples, so it runs in its
// own FreeRTOS task on core 0. The accelerometer loop on core 1 never waits for it.
#pragma once

#include <Arduino.h>

struct Vitals {
    int16_t  heartRate = 0;     // BPM
    int16_t  spo2 = 0;          // %
    bool     hrValid = false;
    bool     spo2Valid = false;
    bool     contact = false;   // sensor is touching skin
    uint32_t updatedMs = 0;     // millis() of the last measurement
    uint32_t sequence = 0;      // increments with every new measurement
};

class PulseMonitor {
public:
    // Starts I2C, configures the sensor and launches the background task. False if not found.
    bool begin();
    bool present() const { return present_; }

    // Thread-safe copy of the latest measurement
    Vitals latest();

private:
    static void taskEntry(void* arg);
    void taskLoop();
    void publish(const Vitals& v);

    bool present_ = false;
    Vitals vitals_;
    portMUX_TYPE mux_ = portMUX_INITIALIZER_UNLOCKED;
    int16_t hrHistory_[3] = {0, 0, 0};
    uint8_t hrCount_ = 0;
};
