#include "accel_mma7361.h"

#include <Preferences.h>
#include <math.h>

#include "config.h"

static const float GRAVITY = 9.80665f;
static const int PINS[3] = {PIN_ACCEL_X, PIN_ACCEL_Y, PIN_ACCEL_Z};
static const char* NVS_NAMESPACE = "mma7361";

void Mma7361::begin() {
    pinMode(PIN_ACCEL_SLEEP, OUTPUT);
    digitalWrite(PIN_ACCEL_SLEEP, HIGH);  // wake up
    pinMode(PIN_ACCEL_GSEL, OUTPUT);
    digitalWrite(PIN_ACCEL_GSEL, ACCEL_RANGE_6G ? HIGH : LOW);
    // Datasheet sensitivity at 3.3 V: 800 mV/g (1.5 g mode) or 206 mV/g (6 g mode)
    sensitivity_ = ACCEL_RANGE_6G ? 206.0f : 800.0f;
    delay(10);

    analogReadResolution(12);
    analogSetAttenuation(ADC_11db);  // full 0-3.3 V range

    if (!loadCalibration()) {
        // Nominal zero-g is half the supply. Works, but calibrating is more accurate.
        for (int i = 0; i < 3; i++) zero_[i] = 1650.0f;
        calibrated_ = false;
    }
}

float Mma7361::readMilliVolts(int pin) {
    uint32_t total = 0;
    for (int i = 0; i < ACCEL_OVERSAMPLE; i++) total += analogReadMilliVolts(pin);
    return (float)total / ACCEL_OVERSAMPLE;
}

bool Mma7361::looksConnected(float mv[3]) {
    bool ok = true;
    for (int i = 0; i < 3; i++) {
        mv[i] = readMilliVolts(PINS[i]);
        if (mv[i] < 300 || mv[i] > 3000) ok = false;
    }
    return ok;
}

Vec3 Mma7361::read() {
    float g[3];
    clipped_ = false;
    for (int i = 0; i < 3; i++) {
        const float mv = readMilliVolts(PINS[i]);
        if (mv < 120 || mv > 3150) clipped_ = true;
        g[i] = (mv - zero_[i]) / sensitivity_ * GRAVITY;
    }
    return Vec3{g[0], g[1], g[2]};
}

bool Mma7361::calibrateFlat() {
    const int samples = 200;
    double sum[3] = {0, 0, 0};
    for (int n = 0; n < samples; n++) {
        for (int i = 0; i < 3; i++) sum[i] += readMilliVolts(PINS[i]);
        delay(5);
    }
    float z[3];
    z[0] = sum[0] / samples;
    z[1] = sum[1] / samples;
    z[2] = sum[2] / samples - sensitivity_;  // Z axis feels +1 g when flat

    // Offsets far from mid-supply usually mean the band wasn't flat or was moving.
    for (int i = 0; i < 3; i++) {
        if (fabsf(z[i] - 1650.0f) > 300.0f) return false;
    }
    for (int i = 0; i < 3; i++) zero_[i] = z[i];
    calibrated_ = true;

    Preferences prefs;
    prefs.begin(NVS_NAMESPACE, false);
    prefs.putFloat("zx", z[0]);
    prefs.putFloat("zy", z[1]);
    prefs.putFloat("zz", z[2]);
    prefs.putBool("range6g", ACCEL_RANGE_6G);
    prefs.end();
    return true;
}

bool Mma7361::loadCalibration() {
    Preferences prefs;
    if (!prefs.begin(NVS_NAMESPACE, true)) return false;
    const bool ok = prefs.isKey("zx") && prefs.getBool("range6g", !ACCEL_RANGE_6G) == ACCEL_RANGE_6G;
    if (ok) {
        zero_[0] = prefs.getFloat("zx", 1650.0f);
        zero_[1] = prefs.getFloat("zy", 1650.0f);
        zero_[2] = prefs.getFloat("zz", 1650.0f);
        calibrated_ = true;
    }
    prefs.end();
    return ok;
}

void Mma7361::offsets(float out[3]) const {
    for (int i = 0; i < 3; i++) out[i] = zero_[i];
}
