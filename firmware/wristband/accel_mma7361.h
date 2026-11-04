// MMA7361 analog accelerometer on the ESP32 ADC.
// Based on the team's original accelerometer_3axis.ino, with calibration saved to flash.
#pragma once

#include <Arduino.h>
#include "rep_detector.h"

class Mma7361 {
public:
    void begin();

    // true if all three axes read sensible voltages (a loose wire reads ~0 V or ~3.3 V)
    bool looksConnected(float mv[3]);

    // Acceleration in m/s^2, gravity included (~9.8 m/s^2 total at rest)
    Vec3 read();

    // true if the last read hit the edge of the sensor range
    bool clipped() const { return clipped_; }

    // Band lying flat, face up, still: X and Y feel 0 g, Z feels +1 g.
    // Stores the zero-g offsets in flash. Returns false if the result looks wrong.
    bool calibrateFlat();
    bool isCalibrated() const { return calibrated_; }
    void offsets(float out[3]) const;

    float sensitivityMvPerG() const { return sensitivity_; }

private:
    float readMilliVolts(int pin);
    bool loadCalibration();

    float zero_[3] = {1650, 1650, 1650};
    float sensitivity_ = 800.0f;
    bool calibrated_ = false;
    bool clipped_ = false;
};
