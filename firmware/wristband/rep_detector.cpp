#include "rep_detector.h"

#include <math.h>

namespace {

const float RAD_TO_DEG_F = 57.2957795f;

inline float lowPass(float current, float target, float dt, float tau) {
    return current + (dt / (tau + dt)) * (target - current);
}

inline void lowPass(Vec3& current, const Vec3& target, float dt, float tau) {
    current.x = lowPass(current.x, target.x, dt, tau);
    current.y = lowPass(current.y, target.y, dt, tau);
    current.z = lowPass(current.z, target.z, dt, tau);
}

inline float length(const Vec3& v) { return sqrtf(v.x * v.x + v.y * v.y + v.z * v.z); }

inline Vec3 normalized(const Vec3& v) {
    float n = length(v);
    if (n < 1e-6f) return Vec3{0, 0, 1};
    return Vec3{v.x / n, v.y / n, v.z / n};
}

inline float dot(const Vec3& a, const Vec3& b) { return a.x * b.x + a.y * b.y + a.z * b.z; }

// Angle in degrees between two directions
inline float angleBetween(const Vec3& a, const Vec3& b) {
    float c = dot(normalized(a), normalized(b));
    if (c > 1.0f) c = 1.0f;
    if (c < -1.0f) c = -1.0f;
    return acosf(c) * RAD_TO_DEG_F;
}

}  // namespace

void RepDetector::configure(const ExerciseProfile& profile, float topDegOverride, float thresholdOverride) {
    profile_ = &profile;
    topDeg_ = topDegOverride > 0 ? topDegOverride : profile.topDeg;
    // A full rep must go clearly past the "returned" angle, otherwise every wobble counts.
    if (profile.mode == DetectMode::Tilt && topDeg_ < profile.returnDeg + 8.0f) {
        topDeg_ = profile.returnDeg + 8.0f;
    }
    threshold_ = thresholdOverride > 0 ? thresholdOverride : profile.threshold;
    reset();
}

void RepDetector::reset() {
    first_ = true;
    lastMs_ = startMs_ = 0;
    gFast_ = gSlow_ = Vec3{0, 0, 0};
    ref_ = Vec3{0, 0, 1};
    dynAvg_ = 0;
    still_ = ready_ = false;
    calm_ = false;
    calmSinceMs_ = 0;
    angle_ = 0;

    inRep_ = reachedTop_ = blocked_ = false;
    repStartMs_ = 0;
    repMaxAngle_ = repPeak_ = 0;

    signal_ = 0;
    axisVar_[0] = axisVar_[1] = axisVar_[2] = 0;
    axis_ = 2;
    lastLobe_ = 0;
    lobes_ = 0;
    lastLobeMs_ = lastRepMs_ = firstLobeMs_ = 0;

    reps_ = partial_ = 0;
    holdMs_ = activeMs_ = totalRepMs_ = 0;
    totalRom_ = sessionPeak_ = 0;
}

bool RepDetector::update(const Vec3& a, uint32_t now, RepEvent& ev) {
    if (profile_ == nullptr) return false;

    if (first_) {
        first_ = false;
        gFast_ = gSlow_ = a;
        lastMs_ = startMs_ = now;
        return false;
    }

    uint32_t dtMs = now - lastMs_;
    if (dtMs == 0) return false;
    lastMs_ = now;
    if (dtMs > 200) dtMs = 200;  // ignore long gaps (e.g. a blocked serial port)
    const float dt = dtMs / 1000.0f;
    dt_ = dt;

    lowPass(gFast_, a, dt, FAST_TAU_S);
    lowPass(gSlow_, a, dt, SLOW_TAU_S);

    const Vec3 dyn{a.x - gSlow_.x, a.y - gSlow_.y, a.z - gSlow_.z};
    const float dynMag = length(dyn);
    if (dynMag > sessionPeak_ && ready_) sessionPeak_ = dynMag;

    // Stillness: average dynamic acceleration stays low for STILL_HOLD_MS
    dynAvg_ = lowPass(dynAvg_, dynMag, dt, STILL_TAU_S);
    if (dynAvg_ < STILL_THRESHOLD) {
        if (!calm_) {
            calm_ = true;
            calmSinceMs_ = now;
        }
        still_ = (now - calmSinceMs_) >= STILL_HOLD_MS;
    } else {
        calm_ = false;
        still_ = false;
    }

    if (ready_ && !still_) activeMs_ += dtMs;

    switch (profile_->mode) {
        case DetectMode::Tilt:
            return updateTilt(now, dynMag, ev);
        case DetectMode::Motion:
            return updateMotion(now, dyn, dynMag, ev);
        case DetectMode::Hold:
            updateHold(now, dtMs);
            return false;
    }
    return false;
}

// ---------- Tilt: start -> top -> back to start ----------
bool RepDetector::updateTilt(uint32_t now, float dynMag, RepEvent& ev) {
    const ExerciseProfile& p = *profile_;

    if (!ready_) {
        // Wait until the patient holds the starting position, then remember it.
        if (still_) {
            ref_ = normalized(gFast_);
            ready_ = true;
        }
        return false;
    }

    angle_ = angleBetween(gFast_, ref_);

    // After a timed-out rep, wait until the arm is back near the start.
    if (blocked_) {
        if (angle_ <= p.returnDeg) blocked_ = false;
        return false;
    }

    if (!inRep_) {
        if (angle_ > p.startDeg) {
            inRep_ = true;
            reachedTop_ = false;
            repStartMs_ = now;
            repMaxAngle_ = angle_;
            repPeak_ = dynMag;
        } else if (still_) {
            // Slowly follow small changes in the resting position so the reference doesn't drift.
            Vec3 g = normalized(gFast_);
            const float k = 0.01f;
            ref_ = normalized(Vec3{ref_.x + k * (g.x - ref_.x), ref_.y + k * (g.y - ref_.y), ref_.z + k * (g.z - ref_.z)});
        }
        return false;
    }

    if (angle_ > repMaxAngle_) repMaxAngle_ = angle_;
    if (dynMag > repPeak_) repPeak_ = dynMag;
    if (angle_ >= topDeg_) reachedTop_ = true;

    const uint32_t duration = now - repStartMs_;

    if (duration > p.maxRepMs) {
        if (repMaxAngle_ > p.returnDeg + 5.0f) partial_++;
        inRep_ = false;
        blocked_ = true;
        return false;
    }

    if (angle_ < p.startDeg && repMaxAngle_ <= p.returnDeg + 5.0f) {
        inRep_ = false;  // just a wobble around the start position
        return false;
    }

    const bool leftStartZone = reachedTop_ || repMaxAngle_ > p.returnDeg + 5.0f;
    if (angle_ <= p.returnDeg && leftStartZone) {
        inRep_ = false;
        if (reachedTop_ && duration >= p.minRepMs) {
            finishRep(duration, repMaxAngle_, repPeak_, ev);
            return true;
        }
        partial_++;  // came back without reaching the target range of motion (or far too fast)
    }
    return false;
}

// ---------- Motion: one positive + one negative acceleration lobe = one rep ----------
bool RepDetector::updateMotion(uint32_t now, const Vec3& dyn, float dynMag, RepEvent& ev) {
    const ExerciseProfile& p = *profile_;

    if (!ready_) {
        if (now - startMs_ < SETTLE_MS) return false;
        ready_ = true;
        ref_ = normalized(gFast_);
    }
    angle_ = angleBetween(gFast_, ref_);

    float raw;
    if (p.axis == MotionAxis::Vertical) {
        raw = dot(dyn, normalized(gSlow_));
    } else {
        const float d[3] = {dyn.x, dyn.y, dyn.z};
        int best = axis_;
        for (int i = 0; i < 3; i++) {
            axisVar_[i] = lowPass(axisVar_[i], d[i] * d[i], dt_, 2.0f);
            if (axisVar_[i] > axisVar_[best]) best = i;
        }
        // Hysteresis so the axis doesn't flip back and forth mid-set
        if (best != axis_ && axisVar_[best] > 1.5f * axisVar_[axis_]) axis_ = best;
        raw = d[axis_];
    }

    signal_ = lowPass(signal_, raw, dt_, SIGNAL_TAU_S);
    if (dynMag > repPeak_) repPeak_ = dynMag;

    // A long pause resets the half-rep bookkeeping so pauses don't shift the count.
    if (lastLobe_ != 0 && now - lastLobeMs_ > p.maxRepMs) {
        lastLobe_ = 0;
        lobes_ = 0;
        lastRepMs_ = 0;
        repPeak_ = 0;
    }

    int8_t lobe = 0;
    if (signal_ > threshold_) lobe = 1;
    else if (signal_ < -threshold_) lobe = -1;

    if (lobe == 0 || lobe == lastLobe_) return false;
    if (lastLobe_ != 0 && now - lastLobeMs_ < p.minRepMs / 4) return false;  // too fast to be real

    if (lobes_ == 0) firstLobeMs_ = now;
    lastLobe_ = lobe;
    lastLobeMs_ = now;
    lobes_++;

    if (lobes_ < 2) return false;

    const uint32_t duration = lastRepMs_ ? now - lastRepMs_ : 2 * (now - firstLobeMs_);
    lobes_ = 0;
    lastRepMs_ = now;
    const float peak = repPeak_;
    repPeak_ = 0;
    if (duration < p.minRepMs) return false;
    finishRep(duration, 0.0f, peak, ev);
    return true;
}

// ---------- Hold: seconds spent still ----------
void RepDetector::updateHold(uint32_t now, uint32_t dtMs) {
    if (!ready_) {
        if (now - startMs_ < SETTLE_MS) return;
        ready_ = true;
        ref_ = normalized(gFast_);
    }
    angle_ = angleBetween(gFast_, ref_);
    if (still_) holdMs_ += dtMs;
}

void RepDetector::finishRep(uint32_t durationMs, float rom, float peak, RepEvent& ev) {
    reps_++;
    totalRepMs_ += durationMs;
    totalRom_ += rom;
    ev.rep = reps_;
    ev.durationMs = durationMs;
    ev.romDeg = rom;
    ev.peakAccel = peak;
}
