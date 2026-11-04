// Rep detector for a wrist-worn 3-axis accelerometer (no gyroscope).
// Plain C++ (no Arduino headers) so it can be unit-tested on a PC: see firmware/test.
//
// Feed it one acceleration sample (m/s^2, gravity included) at a time.
// It keeps two low-pass filtered copies of the signal:
//   gFast  (~0.15 s) : orientation of the wrist, used for the tilt angle
//   gSlow  (~1 s)    : gravity estimate; a - gSlow = dynamic (linear) acceleration
#pragma once

#include <stdint.h>
#include "exercise_profile.h"

struct Vec3 {
    float x, y, z;
};

struct RepEvent {
    uint16_t rep;         // rep number within the set (1, 2, 3, ...)
    uint32_t durationMs;  // time taken by this rep
    float    romDeg;      // tilt mode: largest angle reached; motion mode: tilt swing during the rep
    float    peakAccel;   // largest dynamic acceleration during the rep, m/s^2
};

class RepDetector {
public:
    // topDegOverride / thresholdOverride <= 0 keep the profile's value.
    void configure(const ExerciseProfile& profile, float topDegOverride = 0, float thresholdOverride = 0);
    void reset();

    // Returns true when a rep was completed by this sample and fills `ev`.
    bool update(const Vec3& accel, uint32_t nowMs, RepEvent& ev);

    bool     ready() const { return ready_; }        // start position captured (tilt) / filters settled
    bool     still() const { return still_; }
    bool     moving() const { return !still_; }
    float    angleDeg() const { return angle_; }     // tilt from start position
    float    signal() const { return signal_; }      // motion-mode filtered signal
    uint16_t reps() const { return reps_; }
    uint16_t partialReps() const { return partial_; } // tilt: started but never reached topDeg
    uint32_t holdMs() const { return holdMs_; }
    uint32_t activeMs() const { return activeMs_; }
    float    averageRepMs() const { return reps_ ? (float)totalRepMs_ / reps_ : 0.0f; }
    float    averageRomDeg() const { return reps_ ? totalRom_ / reps_ : 0.0f; }
    float    peakAccel() const { return sessionPeak_; }
    const ExerciseProfile* profile() const { return profile_; }

    // Tuning constants (public so tests can reason about them)
    static constexpr float FAST_TAU_S        = 0.15f;
    static constexpr float SLOW_TAU_S        = 1.0f;
    static constexpr float SIGNAL_TAU_S      = 0.12f;
    static constexpr float STILL_TAU_S       = 0.30f;
    static constexpr float STILL_THRESHOLD   = 0.35f;  // m/s^2 of dynamic acceleration
    static constexpr uint32_t STILL_HOLD_MS  = 600;    // must be calm this long to count as still
    static constexpr uint32_t SETTLE_MS      = 1500;   // filters warm-up for motion/hold modes

private:
    bool updateTilt(uint32_t now, float dynMag, RepEvent& ev);
    bool updateMotion(uint32_t now, const Vec3& dyn, float dynMag, RepEvent& ev);
    void updateHold(uint32_t now, uint32_t dtMs);
    void finishRep(uint32_t durationMs, float rom, float peak, RepEvent& ev);

    const ExerciseProfile* profile_ = nullptr;
    float topDeg_ = 0, threshold_ = 0;

    bool     first_ = true;
    uint32_t lastMs_ = 0, startMs_ = 0;
    Vec3     gFast_{0, 0, 0}, gSlow_{0, 0, 0}, ref_{0, 0, 1};
    float    dynAvg_ = 0;
    bool     still_ = false, ready_ = false, calm_ = false;
    float    dt_ = 0.02f;
    uint32_t calmSinceMs_ = 0;
    float    angle_ = 0;

    // tilt state
    bool     inRep_ = false, reachedTop_ = false, blocked_ = false;
    uint32_t repStartMs_ = 0;
    float    repMaxAngle_ = 0, repPeak_ = 0;

    // motion state
    float    signal_ = 0;
    float    axisVar_[3] = {0, 0, 0};
    int      axis_ = 2;
    int8_t   lastLobe_ = 0;        // +1, -1, or 0 (none yet)
    uint8_t  lobes_ = 0;           // lobes since the last counted rep
    uint32_t lastLobeMs_ = 0, lastRepMs_ = 0, firstLobeMs_ = 0;

    // results
    uint16_t reps_ = 0, partial_ = 0;
    uint32_t holdMs_ = 0, activeMs_ = 0, totalRepMs_ = 0;
    float    totalRom_ = 0, sessionPeak_ = 0;
};
