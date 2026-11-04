// PC unit tests for the band's plain-C++ logic (rep detector, JSON helper, exercise table).
// Build and run:  make -C firmware/test      (needs g++)
#include <math.h>
#include <stdio.h>
#include <string.h>

#include <random>

#include "../wristband/exercise_profile.h"
#include "../wristband/json_lite.h"
#include "../wristband/rep_detector.h"

static int failures = 0;
static int checks = 0;

#define CHECK(cond, ...)                                     \
    do {                                                     \
        checks++;                                            \
        if (!(cond)) {                                       \
            failures++;                                      \
            printf("  FAIL %s:%d: ", __FILE__, __LINE__);    \
            printf(__VA_ARGS__);                             \
            printf("\n");                                    \
        }                                                    \
    } while (0)

static const float G = 9.80665f;
static const float PI_F = 3.14159265f;
static const uint32_t DT_MS = 20;  // 50 Hz, same as the firmware

// ---------- signal helpers ----------

struct Sim {
    RepDetector det;
    uint32_t t = 0;
    std::mt19937 rng{42};
    std::normal_distribution<float> noise{0.0f, 0.08f};  // ~ESP32 ADC noise after oversampling
    int events = 0;
    float lastRom = 0;
    uint32_t lastDuration = 0;

    void feed(Vec3 a) {
        a.x += noise(rng);
        a.y += noise(rng);
        a.z += noise(rng);
        RepEvent ev;
        if (det.update(a, t, ev)) {
            events++;
            lastRom = ev.romDeg;
            lastDuration = ev.durationMs;
        }
        t += DT_MS;
    }
};

// Rotate vector v about unit axis k by angle (Rodrigues)
static Vec3 rotate(Vec3 v, Vec3 k, float angleDeg) {
    float a = angleDeg * PI_F / 180.0f;
    float c = cosf(a), s = sinf(a);
    Vec3 kxv{k.y * v.z - k.z * v.y, k.z * v.x - k.x * v.z, k.x * v.y - k.y * v.x};
    float kdv = k.x * v.x + k.y * v.y + k.z * v.z;
    return Vec3{v.x * c + kxv.x * s + k.x * kdv * (1 - c), v.y * c + kxv.y * s + k.y * kdv * (1 - c),
                v.z * c + kxv.z * s + k.z * kdv * (1 - c)};
}

static Vec3 unit(Vec3 v) {
    float n = sqrtf(v.x * v.x + v.y * v.y + v.z * v.z);
    return Vec3{v.x / n, v.y / n, v.z / n};
}

static void still(Sim& s, Vec3 g, float seconds) {
    for (float t = 0; t < seconds; t += DT_MS / 1000.0f) s.feed(g);
}

// Tilt reps: the gravity direction swings by amplitudeDeg and back, `reps` times.
static void tiltReps(Sim& s, Vec3 g0, Vec3 axis, int reps, float amplitudeDeg, float periodS, float pauseS) {
    for (int r = 0; r < reps; r++) {
        for (float t = 0; t < periodS; t += DT_MS / 1000.0f) {
            float angle = amplitudeDeg * 0.5f * (1 - cosf(2 * PI_F * t / periodS));
            s.feed(rotate(g0, axis, angle));
        }
        still(s, g0, pauseS);
    }
}

// Linear back-and-forth motion along `dir` with displacement amplitude `meters`.
static void linearReps(Sim& s, Vec3 g0, Vec3 dir, int reps, float meters, float periodS, float pauseS) {
    float w = 2 * PI_F / periodS;
    for (int r = 0; r < reps; r++) {
        for (float t = 0; t < periodS; t += DT_MS / 1000.0f) {
            // x(t) = meters/2 * (1 - cos wt)  ->  a(t) = meters/2 * w^2 * cos wt
            float acc = meters * 0.5f * w * w * cosf(w * t);
            s.feed(Vec3{g0.x + dir.x * acc, g0.y + dir.y * acc, g0.z + dir.z * acc});
        }
        still(s, g0, pauseS);
    }
}

static const ExerciseProfile& profile(const char* id) {
    const ExerciseProfile* p = findExercise(id);
    if (!p) {
        printf("missing exercise %s\n", id);
        static ExerciseProfile dummy{"?", "reps", DetectMode::Hold, MotionAxis::Vertical, 0, 0, 0, 0, 0, 0};
        return dummy;
    }
    return *p;
}

// ---------- tests ----------

static void test_tilt_curls() {
    printf("tilt: bicep curls\n");
    Sim s;
    s.det.configure(profile("bicep_curl"));
    Vec3 g{0, 0, G};
    still(s, g, 2.0f);
    CHECK(s.det.ready(), "start position should be captured after holding still");
    tiltReps(s, g, Vec3{0, 1, 0}, 12, 120, 2.5f, 0.5f);
    still(s, g, 1.0f);
    CHECK(s.det.reps() == 12, "expected 12 reps, got %d", s.det.reps());
    CHECK(s.det.partialReps() == 0, "expected 0 partial reps, got %d", s.det.partialReps());
    CHECK(fabsf(s.lastRom - 120) < 10, "ROM should be ~120 deg, got %.1f", s.lastRom);
    CHECK(s.det.averageRepMs() > 1500 && s.det.averageRepMs() < 2600, "avg rep %.0f ms", s.det.averageRepMs());
}

static void test_tilt_any_orientation() {
    printf("tilt: band worn at an odd angle, front raises\n");
    Sim s;
    s.det.configure(profile("front_raise"));
    Vec3 g0 = unit(Vec3{0.5f, 0.6f, 0.3f});
    g0 = Vec3{g0.x * G, g0.y * G, g0.z * G};
    Vec3 axis = unit(Vec3{0.6f, -0.5f, 0.0f});  // perpendicular to g0
    still(s, g0, 2.0f);
    tiltReps(s, g0, axis, 10, 85, 3.0f, 0.8f);
    still(s, g0, 1.0f);
    CHECK(s.det.reps() == 10, "expected 10 reps, got %d", s.det.reps());
}

static void test_tilt_partial() {
    printf("tilt: reps that don't reach the target range count as partial\n");
    Sim s;
    s.det.configure(profile("bicep_curl"));
    Vec3 g{0, 0, G};
    still(s, g, 2.0f);
    tiltReps(s, g, Vec3{1, 0, 0}, 6, 45, 2.5f, 0.5f);
    CHECK(s.det.reps() == 0, "expected 0 full reps, got %d", s.det.reps());
    CHECK(s.det.partialReps() == 6, "expected 6 partial reps, got %d", s.det.partialReps());
}

static void test_tilt_top_override() {
    printf("tilt: clinician-set smaller range of motion\n");
    Sim s;
    s.det.configure(profile("bicep_curl"), 40.0f);
    Vec3 g{0, 0, G};
    still(s, g, 2.0f);
    tiltReps(s, g, Vec3{1, 0, 0}, 6, 50, 2.5f, 0.5f);
    CHECK(s.det.reps() == 6, "expected 6 reps with top_deg=40, got %d", s.det.reps());
}

static void test_motion_vertical() {
    printf("motion: shoulder press (vertical)\n");
    Sim s;
    s.det.configure(profile("shoulder_press"));
    Vec3 g0 = unit(Vec3{0.2f, -0.3f, 0.93f});
    Vec3 up = g0;
    g0 = Vec3{g0.x * G, g0.y * G, g0.z * G};
    still(s, g0, 2.0f);
    linearReps(s, g0, up, 10, 0.35f, 3.0f, 0.3f);
    still(s, g0, 2.0f);
    CHECK(s.det.reps() == 10, "expected 10 reps, got %d", s.det.reps());
}

static void test_motion_slow_squats() {
    printf("motion: slow squats (4 s per rep, 0.3 m)\n");
    Sim s;
    s.det.configure(profile("goblet_squat"));
    Vec3 g0{0, G, 0};
    still(s, g0, 2.0f);
    linearReps(s, g0, Vec3{0, 1, 0}, 8, 0.30f, 4.0f, 1.0f);
    still(s, g0, 2.0f);
    CHECK(s.det.reps() == 8, "expected 8 reps, got %d", s.det.reps());
}

static void test_motion_dominant_axis() {
    printf("motion: seated row (horizontal, dominant axis)\n");
    Sim s;
    s.det.configure(profile("seated_row"));
    Vec3 g0{0, 0, G};
    still(s, g0, 2.0f);
    linearReps(s, g0, Vec3{0, 1, 0}, 12, 0.35f, 2.5f, 0.3f);
    still(s, g0, 2.0f);
    CHECK(s.det.reps() == 12, "expected 12 reps, got %d", s.det.reps());
}

static void test_motion_pause_mid_set() {
    printf("motion: a long pause in the middle of a set\n");
    Sim s;
    s.det.configure(profile("chest_press"));
    Vec3 g0{0, 0, G};
    still(s, g0, 2.0f);
    linearReps(s, g0, Vec3{0, 0, 1}, 5, 0.35f, 2.5f, 0.3f);
    still(s, g0, 12.0f);
    linearReps(s, g0, Vec3{0, 0, 1}, 5, 0.35f, 2.5f, 0.3f);
    still(s, g0, 2.0f);
    CHECK(s.det.reps() == 10, "expected 10 reps, got %d", s.det.reps());
}

static void test_motion_tiny_movement_ignored() {
    printf("motion: fidgeting below threshold is ignored\n");
    Sim s;
    s.det.configure(profile("shoulder_press"));
    Vec3 g0{0, 0, G};
    still(s, g0, 2.0f);
    linearReps(s, g0, Vec3{0, 0, 1}, 10, 0.03f, 2.0f, 0.0f);
    CHECK(s.det.reps() == 0, "expected 0 reps, got %d", s.det.reps());
}

static void test_noise_only() {
    printf("all modes: 30 s of sensor noise gives no reps\n");
    for (int i = 0; i < EXERCISE_COUNT; i++) {
        Sim s;
        s.det.configure(EXERCISES[i]);
        still(s, Vec3{0, 0, G}, 30.0f);
        CHECK(s.det.reps() == 0, "%s counted %d reps from noise", EXERCISES[i].id, s.det.reps());
    }
}

static void test_heavy_noise_and_seeds() {
    printf("all modes: heavier noise (0.15 m/s^2), several random seeds\n");
    for (unsigned seed = 1; seed <= 5; seed++) {
        for (int i = 0; i < EXERCISE_COUNT; i++) {
            Sim s;
            s.rng.seed(seed);
            s.noise = std::normal_distribution<float>(0.0f, 0.15f);
            s.det.configure(EXERCISES[i]);
            still(s, Vec3{0, 0, G}, 20.0f);
            CHECK(s.det.reps() == 0, "%s seed %u counted %d reps from noise", EXERCISES[i].id, seed, s.det.reps());
        }
    }
    // real reps still counted exactly with heavier noise
    for (unsigned seed = 1; seed <= 5; seed++) {
        Sim s;
        s.rng.seed(seed);
        s.noise = std::normal_distribution<float>(0.0f, 0.15f);
        s.det.configure(profile("shoulder_press"));
        Vec3 g0{0, 0, G};
        still(s, g0, 2.0f);
        linearReps(s, g0, Vec3{0, 0, 1}, 10, 0.35f, 3.0f, 0.3f);
        still(s, g0, 2.0f);
        CHECK(s.det.reps() == 10, "seed %u: expected 10 presses, got %d", seed, s.det.reps());
    }
}

static void test_hold() {
    printf("hold: wall sit timer\n");
    Sim s;
    s.det.configure(profile("wall_sit"));
    Vec3 g0{0, G, 0};
    still(s, g0, 20.0f);
    float held = s.det.holdMs() / 1000.0f;
    CHECK(held > 17.0f && held <= 20.0f, "expected ~18 s held, got %.1f", held);
    // moving stops the timer
    uint32_t before = s.det.holdMs();
    linearReps(s, g0, Vec3{0, 1, 0}, 3, 0.4f, 1.5f, 0.0f);
    CHECK(s.det.holdMs() - before < 1000, "timer should pause while moving (+%u ms)", s.det.holdMs() - before);
}

static void test_carry_steps() {
    printf("motion: farmer's carry counts steps\n");
    Sim s;
    s.det.configure(profile("farmers_carry"));
    Vec3 g0{0, 0, G};
    still(s, g0, 2.0f);
    linearReps(s, g0, Vec3{0, 0, 1}, 30, 0.05f, 0.55f, 0.0f);  // ~1.8 steps/s, 5 cm bounce
    still(s, g0, 2.0f);
    CHECK(s.det.reps() >= 28 && s.det.reps() <= 30, "expected ~30 steps, got %d", s.det.reps());
}

static void test_reset() {
    printf("reset clears counts\n");
    Sim s;
    s.det.configure(profile("bicep_curl"));
    Vec3 g{0, 0, G};
    still(s, g, 2.0f);
    tiltReps(s, g, Vec3{0, 1, 0}, 3, 120, 2.0f, 0.5f);
    CHECK(s.det.reps() == 3, "expected 3, got %d", s.det.reps());
    s.det.reset();
    CHECK(s.det.reps() == 0 && !s.det.ready(), "reset should clear reps and ready");
}

static void test_exercise_table() {
    printf("exercise table\n");
    CHECK(EXERCISE_COUNT > 20, "expected the wrist exercise table, got %d entries", EXERCISE_COUNT);
    CHECK(findExercise("bicep_curl") != nullptr, "bicep_curl missing");
    CHECK(findExercise("push_up") == nullptr, "push_up is camera-only and must not be in the band table");
    CHECK(findExercise(nullptr) == nullptr, "null id");
    for (int i = 0; i < EXERCISE_COUNT; i++) {
        const ExerciseProfile& p = EXERCISES[i];
        if (p.mode == DetectMode::Tilt) {
            CHECK(p.startDeg < p.returnDeg && p.returnDeg < p.topDeg, "%s tilt thresholds out of order", p.id);
        }
        if (p.mode != DetectMode::Hold) {
            CHECK(p.minRepMs > 0 && p.maxRepMs > p.minRepMs, "%s rep timing invalid", p.id);
        }
        if (p.mode == DetectMode::Motion) CHECK(p.threshold > 0, "%s needs a threshold", p.id);
    }
}

static void test_json() {
    printf("json_lite\n");
    const char* cmd = "{\"cmd\":\"start\", \"exercise\" : \"bicep_curl\",\"set\":2,\"target\":12,"
                      "\"top_deg\":55.5,\"raw\":true,\"note\":\"say \\\"hi\\\"\"}";
    char buf[32];
    float f;
    bool b;
    CHECK(jsonGetString(cmd, "cmd", buf, sizeof buf) && strcmp(buf, "start") == 0, "cmd=%s", buf);
    CHECK(jsonGetString(cmd, "exercise", buf, sizeof buf) && strcmp(buf, "bicep_curl") == 0, "exercise=%s", buf);
    CHECK(jsonGetNumber(cmd, "set", &f) && f == 2, "set");
    CHECK(jsonGetNumber(cmd, "top_deg", &f) && fabsf(f - 55.5f) < 1e-4, "top_deg");
    CHECK(jsonGetBool(cmd, "raw", &b) && b, "raw");
    CHECK(jsonGetString(cmd, "note", buf, sizeof buf) && strcmp(buf, "say \"hi\"") == 0, "escaped=%s", buf);
    CHECK(!jsonGetNumber(cmd, "missing", &f), "missing key");
    CHECK(!jsonGetString(cmd, "set", buf, sizeof buf), "number is not a string");
    // a key name that appears as a value must not match
    const char* tricky = "{\"cmd\":\"set\",\"set\":5}";
    CHECK(jsonGetNumber(tricky, "set", &f) && f == 5, "value/key confusion");
    char small[4];
    CHECK(jsonGetString(cmd, "exercise", small, sizeof small) && strcmp(small, "bic") == 0, "truncation");
}

int main() {
    test_exercise_table();
    test_json();
    test_tilt_curls();
    test_tilt_any_orientation();
    test_tilt_partial();
    test_tilt_top_override();
    test_motion_vertical();
    test_motion_slow_squats();
    test_motion_dominant_axis();
    test_motion_pause_mid_set();
    test_motion_tiny_movement_ignored();
    test_noise_only();
    test_heavy_noise_and_seeds();
    test_hold();
    test_carry_steps();
    test_reset();
    printf("\n%d checks, %d failures\n", checks, failures);
    return failures ? 1 : 0;
}
