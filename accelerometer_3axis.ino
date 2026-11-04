/*
  Health Band - MMA7361 analog accelerometer on ESP32

  WIRING (MMA7361 breakout -> ESP32)
    X   -> GPIO 34   (ADC1 pin, works while Bluetooth/Wi-Fi is on)
    Y   -> GPIO 35   (ADC1 pin)
    Z   -> GPIO 32   (ADC1 pin)
    SL  -> GPIO 25   (sleep pin: HIGH = awake. Or tie directly to 3.3V)
    GS  -> GPIO 26   (g-select: HIGH = +/-6g. Or tie directly to 3.3V)
    VCC -> 3.3V      (use the breakout's 3.3V pin if it has one)
    GND -> GND
    0G and ST pins can be left unconnected.

  OUTPUT
    CSV at 50 Hz: time_ms,ax,ay,az,magnitude,pitch_deg,roll_deg
    Acceleration is in m/s^2 and includes gravity (~9.8 at rest).
    Lines starting with '#' are status messages. In Python, load with:
      pandas.read_csv("data.csv", comment="#")
*/

#include <Arduino.h>
#include <math.h>

// ---------- Pins ----------
const int PIN_X       = 34;
const int PIN_Y       = 35;
const int PIN_Z       = 32;
const int PIN_SLEEP   = 25;
const int PIN_GSELECT = 26;

// ---------- Sensor constants ----------
// Datasheet sensitivity: 800 mV/g in 1.5g mode, 206 mV/g in 6g mode
const float SENSITIVITY_MV_PER_G = 206.0;
const float GRAVITY              = 9.80665;

// ---------- Sampling ----------
const unsigned long SAMPLE_INTERVAL_MS = 20;   // 50 Hz
const int OVERSAMPLE                   = 8;    // readings averaged per axis to reduce ADC noise
const int CALIBRATION_SAMPLES          = 200;  // about 1 second of still data

// Zero-g voltage for each axis (nominally half the supply, ~1650 mV).
// Replaced by measured values during calibration.
float zeroX = 1650.0;
float zeroY = 1650.0;
float zeroZ = 1650.0;

unsigned long lastSampleTime = 0;

// Read one axis several times and return the average in millivolts.
// analogReadMilliVolts() uses the ESP32's factory calibration,
// which is more accurate than converting raw analogRead() values yourself.
float readAxisMilliVolts(int pin) {
    uint32_t total = 0;
    for (int i = 0; i < OVERSAMPLE; i++) {
        total += analogReadMilliVolts(pin);
    }
    return (float)total / OVERSAMPLE;
}

// Check that the sensor is outputting sensible voltages.
// A disconnected wire or a sleeping sensor usually reads near 0 V or near 3.3 V.
bool sensorLooksConnected() {
    float x = readAxisMilliVolts(PIN_X);
    float y = readAxisMilliVolts(PIN_Y);
    float z = readAxisMilliVolts(PIN_Z);

    bool ok = true;
    if (x < 500 || x > 2800) ok = false;
    if (y < 500 || y > 2800) ok = false;
    if (z < 500 || z > 2800) ok = false;

    Serial.printf("# Raw check (mV): X=%.0f Y=%.0f Z=%.0f\n", x, y, z);
    return ok;
}

// Calibrate with the band lying FLAT and STILL, face up.
// In that position X and Y feel 0g and Z feels +1g, so:
//   zero-g for X and Y = their average reading
//   zero-g for Z       = its average reading minus 1g worth of millivolts
void calibrate() {
    Serial.println("# Calibrating: place the band flat, face up, and keep it still...");
    delay(2000);

    double sumX = 0, sumY = 0, sumZ = 0;
    for (int i = 0; i < CALIBRATION_SAMPLES; i++) {
        sumX += readAxisMilliVolts(PIN_X);
        sumY += readAxisMilliVolts(PIN_Y);
        sumZ += readAxisMilliVolts(PIN_Z);
        delay(5);
    }

    zeroX = sumX / CALIBRATION_SAMPLES;
    zeroY = sumY / CALIBRATION_SAMPLES;
    zeroZ = (sumZ / CALIBRATION_SAMPLES) - SENSITIVITY_MV_PER_G;

    Serial.printf("# Zero-g offsets (mV): X=%.1f Y=%.1f Z=%.1f\n", zeroX, zeroY, zeroZ);

    // Offsets far from ~1650 mV usually mean the band wasn't flat or still
    if (fabs(zeroX - 1650) > 250 || fabs(zeroY - 1650) > 250 || fabs(zeroZ - 1650) > 250) {
        Serial.println("# Warning: offsets look unusual. Was the band flat and still? Restart to recalibrate.");
    }
}

// Convert a millivolt reading to m/s^2 using that axis's zero-g offset
float toMetersPerSecondSquared(float milliVolts, float zeroG) {
    return ((milliVolts - zeroG) / SENSITIVITY_MV_PER_G) * GRAVITY;
}

void setup() {
    Serial.begin(115200);
    delay(500);

    // Wake the sensor and select the +/-6g range
    pinMode(PIN_SLEEP, OUTPUT);
    digitalWrite(PIN_SLEEP, HIGH);
    pinMode(PIN_GSELECT, OUTPUT);
    digitalWrite(PIN_GSELECT, HIGH);
    delay(10);  // give the sensor a moment to wake up

    // Measure the full 0-3.3 V range on the analog pins
    analogReadResolution(12);
    analogSetAttenuation(ADC_11db);

    if (!sensorLooksConnected()) {
        Serial.println("# MMA7361 not responding! Check X/Y/Z wiring, power, and that SL is HIGH.");
        while (1) {
            delay(10);
        }
    }

    calibrate();

    Serial.println("# Health Band Started!");
    Serial.println("time_ms,ax,ay,az,magnitude,pitch_deg,roll_deg");
}

void loop() {
    unsigned long now = millis();

    // Take a reading at a fixed interval instead of using delay()
    if (now - lastSampleTime >= SAMPLE_INTERVAL_MS) {
        lastSampleTime = now;

        float ax = toMetersPerSecondSquared(readAxisMilliVolts(PIN_X), zeroX);
        float ay = toMetersPerSecondSquared(readAxisMilliVolts(PIN_Y), zeroY);
        float az = toMetersPerSecondSquared(readAxisMilliVolts(PIN_Z), zeroZ);

        // Total acceleration: ~9.8 when still, higher or lower during movement.
        // Useful for rep counting since it doesn't depend on wrist orientation.
        float magnitude = sqrt(ax * ax + ay * ay + az * az);

        // Tilt estimated from the direction of gravity.
        // Only reliable during slow movement or holds, since fast motion
        // adds acceleration on top of gravity.
        float pitch = atan2(-ax, sqrt(ay * ay + az * az)) * 180.0 / PI;
        float roll  = atan2(ay, az) * 180.0 / PI;

        Serial.print(now);          Serial.print(",");
        Serial.print(ax, 3);        Serial.print(",");
        Serial.print(ay, 3);        Serial.print(",");
        Serial.print(az, 3);        Serial.print(",");
        Serial.print(magnitude, 3); Serial.print(",");
        Serial.print(pitch, 1);     Serial.print(",");
        Serial.println(roll, 1);
    }
}
