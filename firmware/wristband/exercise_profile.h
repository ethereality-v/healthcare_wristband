// Exercise profile used by the rep detector.
// Plain C++ (no Arduino headers) so it can be unit-tested on a PC.
#pragma once

#include <stdint.h>

enum class DetectMode : uint8_t {
    Tilt,    // angle from the start position: curls, raises, flies, swings
    Motion,  // acceleration cycles: presses, squats, rows, rotations, carries
    Hold     // seconds spent still: wall sits
};

enum class MotionAxis : uint8_t {
    Vertical,  // along gravity (presses, squats, steps)
    Dominant   // whichever sensor axis moves the most (rows, rotations)
};

struct ExerciseProfile {
    const char* id;
    const char* unit;       // "reps", "steps" or "seconds"
    DetectMode  mode;
    MotionAxis  axis;
    float       startDeg;   // tilt: a rep starts past this angle
    float       topDeg;     // tilt: angle that must be reached for a full rep
    float       returnDeg;  // tilt: back below this angle = rep finished
    float       threshold;  // motion: hysteresis threshold in m/s^2
    uint16_t    minRepMs;
    uint16_t    maxRepMs;
};

// Generated from shared/exercises.json (see tools/gen_exercise_table.py)
extern const ExerciseProfile EXERCISES[];
extern const int EXERCISE_COUNT;

// Returns nullptr if the id is unknown.
const ExerciseProfile* findExercise(const char* id);
