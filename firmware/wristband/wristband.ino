/*
  Healthcare Wristband - ESP32 firmware (ECE 198, team GMI)

  Counts exercise reps with an MMA7361 accelerometer and measures heart rate / SpO2 with a
  GY-MAX30102, then streams everything to the laptop app as one JSON object per line.

  Hardware and wiring : hardware/wiring.md
  Message protocol    : docs/protocol.md
  Settings            : config.h (pins, sensor range), secrets.h (Wi-Fi, optional)

  Arduino IDE setup:
    1. Boards Manager: install "esp32 by Espressif Systems"; board = "ESP32 Dev Module"
    2. Library Manager: install "DFRobot_MAX30102"
    3. Open this folder's wristband.ino and upload. Serial Monitor at 115200 baud.

  Quick test from the Serial Monitor (set line ending to "Newline"):
    {"cmd":"start","exercise":"bicep_curl","target":10}
    {"cmd":"stop"}

  First-time calibration: lay the band flat, face up, and hold the BOOT button for 2 seconds
  (or send {"cmd":"calibrate"}). The result is saved in flash.
*/

#include <Arduino.h>

#include "accel_mma7361.h"
#include "band_link.h"
#include "config.h"
#include "exercise_profile.h"
#include "json_lite.h"
#include "pulse_max30102.h"
#include "rep_detector.h"
#include "status_led.h"

Mma7361 accel;
PulseMonitor pulse;
BandLink bandLink;
StatusLed led;
RepDetector detector;

enum class BandState { Idle, Active };
BandState state = BandState::Idle;

// Current set (sent by the laptop with the "start" command)
char exerciseId[32] = "";
int setNumber = 0;
int targetCount = 0;          // reps / steps / seconds
int hrMax = 0;                // 0 = no limit on the band itself
bool targetAnnounced = false;
bool readyAnnounced = false;
uint32_t setStartMs = 0;

bool rawStream = false;
bool laptopAlert = false;     // STOP alert requested by the laptop
bool bandAlert = false;       // STOP alert raised by the band (hr_max exceeded)
uint32_t lastVitalsSeq = 0;
Vec3 lastAccel{0, 0, 0};

uint32_t lastSampleMs = 0;
uint32_t lastStatusMs = 0;
uint32_t buttonDownMs = 0;

// Forward declarations (so the Arduino builder doesn't have to guess prototypes)
const char* stateName();
void updateLedMode();
int currentCount();
void sendHello();
void sendExerciseList();
void sendError(const char* msg);
void finishSet();
void runCalibration();
void handleCommand(const char* line);
void setup();
void loop();

// ---------- helpers ----------

const char* stateName() {
    if (state == BandState::Idle) return "idle";
    return detector.ready() ? "active" : "waiting_still";
}

void updateLedMode() {
    if (laptopAlert || bandAlert) led.setMode(StatusLed::Mode::Alert);
    else if (state == BandState::Idle) led.setMode(StatusLed::Mode::Idle);
    else if (!detector.ready()) led.setMode(StatusLed::Mode::WaitingStill);
    else led.setMode(StatusLed::Mode::Active);
}

int currentCount() {
    const ExerciseProfile* p = detector.profile();
    if (p && p->mode == DetectMode::Hold) return (int)(detector.holdMs() / 1000);
    return detector.reps();
}

void sendHello() {
    float off[3];
    accel.offsets(off);
    bandLink.sendf("{\"type\":\"hello\",\"device\":\"%s\",\"fw\":\"%s\",\"accel\":\"MMA7361\",\"range_g\":%s,"
               "\"calibrated\":%s,\"offsets_mv\":[%.0f,%.0f,%.0f],\"pulse\":%s,\"wifi\":%s,\"exercises\":%d}",
               bandLink.deviceId(), FIRMWARE_VERSION, ACCEL_RANGE_6G ? "6" : "1.5",
               accel.isCalibrated() ? "true" : "false", off[0], off[1], off[2],
               pulse.present() ? "true" : "false", bandLink.wifiConnected() ? "true" : "false", EXERCISE_COUNT);
}

void sendExerciseList() {
    String msg = "{\"type\":\"exercises\",\"ids\":[";
    for (int i = 0; i < EXERCISE_COUNT; i++) {
        if (i) msg += ",";
        msg += "\"";
        msg += EXERCISES[i].id;
        msg += "\"";
    }
    msg += "]}";
    bandLink.send(msg.c_str());
}

void sendError(const char* msg) {
    bandLink.sendf("{\"type\":\"error\",\"msg\":\"%s\"}", msg);
}

void finishSet() {
    if (state != BandState::Active) return;
    const ExerciseProfile* p = detector.profile();
    bandLink.sendf("{\"type\":\"set_done\",\"exercise\":\"%s\",\"set\":%d,\"unit\":\"%s\",\"count\":%d,"
               "\"partial\":%u,\"target\":%d,\"duration_ms\":%lu,\"active_ms\":%lu,\"avg_rep_ms\":%.0f,"
               "\"avg_rom_deg\":%.1f,\"peak_accel\":%.2f}",
               exerciseId, setNumber, p ? p->unit : "reps", currentCount(), detector.partialReps(), targetCount,
               (unsigned long)(millis() - setStartMs), (unsigned long)detector.activeMs(),
               detector.averageRepMs(), detector.averageRomDeg(), detector.peakAccel());
    state = BandState::Idle;
    bandAlert = false;
}

void runCalibration() {
    bandLink.send("{\"type\":\"log\",\"msg\":\"calibrating: keep the band flat, face up and still\"}");
    led.setMode(StatusLed::Mode::WaitingStill);
    led.update(millis());
    delay(1500);
    if (accel.calibrateFlat()) {
        float off[3];
        accel.offsets(off);
        bandLink.sendf("{\"type\":\"calibrated\",\"offsets_mv\":[%.1f,%.1f,%.1f]}", off[0], off[1], off[2]);
        led.flash(3);
    } else {
        sendError("calibration failed: was the band flat, face up and still?");
    }
}

// ---------- commands from the laptop ----------

void handleCommand(const char* line) {
    char cmd[24];
    if (!jsonGetString(line, "cmd", cmd, sizeof(cmd))) {
        sendError("expected {\\\"cmd\\\":...}");
        return;
    }

    if (strcmp(cmd, "ping") == 0 || strcmp(cmd, "hello") == 0) {
        sendHello();
    } else if (strcmp(cmd, "list") == 0) {
        sendExerciseList();
    } else if (strcmp(cmd, "start") == 0) {
        char id[32];
        if (!jsonGetString(line, "exercise", id, sizeof(id))) {
            sendError("start needs \\\"exercise\\\"");
            return;
        }
        const ExerciseProfile* p = findExercise(id);
        if (p == nullptr) {
            bandLink.sendf("{\"type\":\"error\",\"msg\":\"unknown exercise\",\"exercise\":\"%s\"}", id);
            return;
        }
        if (state == BandState::Active) finishSet();

        float v = 0, topDeg = 0, threshold = 0;
        setNumber = jsonGetNumber(line, "set", &v) ? (int)v : 1;
        targetCount = jsonGetNumber(line, "target", &v) ? (int)v : 0;
        hrMax = jsonGetNumber(line, "hr_max", &v) ? (int)v : 0;
        jsonGetNumber(line, "top_deg", &topDeg);
        jsonGetNumber(line, "threshold", &threshold);

        strncpy(exerciseId, id, sizeof(exerciseId) - 1);
        exerciseId[sizeof(exerciseId) - 1] = '\0';
        detector.configure(*p, topDeg, threshold);
        state = BandState::Active;
        setStartMs = millis();
        targetAnnounced = false;
        readyAnnounced = false;
        bandAlert = false;
        bandLink.sendf("{\"type\":\"started\",\"exercise\":\"%s\",\"set\":%d,\"target\":%d,\"unit\":\"%s\"}",
                   exerciseId, setNumber, targetCount, p->unit);
    } else if (strcmp(cmd, "stop") == 0) {
        if (state == BandState::Active) finishSet();
        else bandLink.send("{\"type\":\"log\",\"msg\":\"no set running\"}");
    } else if (strcmp(cmd, "calibrate") == 0) {
        if (state == BandState::Active) sendError("stop the set before calibrating");
        else runCalibration();
    } else if (strcmp(cmd, "alert") == 0) {
        char level[12] = "";
        jsonGetString(line, "level", level, sizeof(level));
        laptopAlert = strcmp(level, "stop") == 0;
        if (strcmp(level, "warn") == 0) led.flash(2);
        if (strcmp(level, "none") == 0) bandAlert = false;
    } else if (strcmp(cmd, "raw") == 0) {
        bool on = false;
        jsonGetBool(line, "on", &on);
        rawStream = on;
    } else {
        bandLink.sendf("{\"type\":\"error\",\"msg\":\"unknown command\",\"cmd\":\"%s\"}", cmd);
    }
}

// ---------- main ----------

void setup() {
    bandLink.begin();
    delay(300);
    led.begin(PIN_LED);
    pinMode(PIN_BUTTON, INPUT_PULLUP);

    accel.begin();
    float mv[3];
    if (!accel.looksConnected(mv)) {
        bandLink.sendf("{\"type\":\"error\",\"msg\":\"MMA7361 not responding: check X/Y/Z wiring, 3.3V, GND and SL\","
                   "\"mv\":[%.0f,%.0f,%.0f]}", mv[0], mv[1], mv[2]);
    }
    if (!accel.isCalibrated()) {
        bandLink.send("{\"type\":\"log\",\"msg\":\"accelerometer not calibrated: lay the band flat and hold BOOT for 2 s\"}");
    }

    if (!pulse.begin()) {
        bandLink.send("{\"type\":\"error\",\"msg\":\"MAX30102 not found: check SDA=21, SCL=22, VIN, GND\"}");
    }

    sendHello();
}

void loop() {
    const uint32_t now = millis();
    bandLink.maintain();

    // Commands
    char line[256];
    while (bandLink.poll(line, sizeof(line))) handleCommand(line);

    // BOOT button held for 2 s -> calibrate (only between sets)
    if (digitalRead(PIN_BUTTON) == LOW) {
        if (buttonDownMs == 0) buttonDownMs = now;
        if (now - buttonDownMs > 2000 && state == BandState::Idle) {
            runCalibration();
            buttonDownMs = 0;
            while (digitalRead(PIN_BUTTON) == LOW) delay(10);
        }
    } else {
        buttonDownMs = 0;
    }

    // Accelerometer at 50 Hz
    if (now - lastSampleMs >= SAMPLE_INTERVAL_MS) {
        lastSampleMs = now;
        lastAccel = accel.read();

        if (rawStream) {
            bandLink.sendf("{\"type\":\"raw\",\"t\":%lu,\"ax\":%.3f,\"ay\":%.3f,\"az\":%.3f}", (unsigned long)now,
                       lastAccel.x, lastAccel.y, lastAccel.z);
        }

        if (state == BandState::Active) {
            RepEvent ev;
            if (detector.update(lastAccel, now, ev)) {
                bandLink.sendf("{\"type\":\"rep\",\"exercise\":\"%s\",\"set\":%d,\"rep\":%u,\"duration_ms\":%lu,"
                           "\"rom_deg\":%.1f,\"peak_accel\":%.2f,\"t\":%lu}",
                           exerciseId, setNumber, ev.rep, (unsigned long)ev.durationMs, ev.romDeg, ev.peakAccel,
                           (unsigned long)now);
                led.flash(1);
            }
            if (detector.ready() && !readyAnnounced) {
                readyAnnounced = true;
                bandLink.sendf("{\"type\":\"ready\",\"exercise\":\"%s\",\"set\":%d}", exerciseId, setNumber);
            }
            if (targetCount > 0 && !targetAnnounced && currentCount() >= targetCount) {
                targetAnnounced = true;
                bandLink.sendf("{\"type\":\"target_reached\",\"exercise\":\"%s\",\"set\":%d,\"count\":%d}", exerciseId,
                           setNumber, currentCount());
                led.flash(3);
            }
        }
    }

    // New heart rate / SpO2 measurement from the core-0 task
    if (pulse.present()) {
        const Vitals v = pulse.latest();
        if (v.sequence != lastVitalsSeq) {
            lastVitalsSeq = v.sequence;
            bandLink.sendf("{\"type\":\"vitals\",\"hr\":%d,\"spo2\":%d,\"hr_valid\":%s,\"spo2_valid\":%s,"
                       "\"contact\":%s,\"moving\":%s,\"t\":%lu}",
                       v.heartRate, v.spo2, v.hrValid ? "true" : "false", v.spo2Valid ? "true" : "false",
                       v.contact ? "true" : "false",
                       (state == BandState::Active && detector.moving()) ? "true" : "false",
                       (unsigned long)v.updatedMs);
            // Safety even without the laptop: flash STOP if heart rate passes the prescribed maximum
            if (hrMax > 0 && v.hrValid && v.heartRate > hrMax && !bandAlert) {
                bandAlert = true;
                bandLink.sendf("{\"type\":\"alert\",\"level\":\"stop\",\"reason\":\"hr_above_max\",\"hr\":%d,\"hr_max\":%d}",
                           v.heartRate, hrMax);
            } else if (bandAlert && v.hrValid && v.heartRate < hrMax - 10) {
                bandAlert = false;
                bandLink.send("{\"type\":\"alert\",\"level\":\"none\",\"reason\":\"hr_recovered\"}");
            }
        }
    }

    // Periodic status
    if (now - lastStatusMs >= STATUS_INTERVAL_MS) {
        lastStatusMs = now;
        const Vitals v = pulse.latest();
        float battery = -1;
        if (PIN_BATTERY >= 0) battery = analogReadMilliVolts(PIN_BATTERY) * BATTERY_DIVIDER / 1000.0f;
        bandLink.sendf("{\"type\":\"status\",\"t\":%lu,\"state\":\"%s\",\"exercise\":\"%s\",\"set\":%d,\"count\":%d,"
                   "\"partial\":%u,\"target\":%d,\"angle\":%.1f,\"moving\":%s,\"hr\":%d,\"spo2\":%d,\"contact\":%s,"
                   "\"alert\":%s,\"clipped\":%s,\"battery_v\":%.2f}",
                   (unsigned long)now, stateName(), state == BandState::Active ? exerciseId : "", setNumber,
                   state == BandState::Active ? currentCount() : 0, detector.partialReps(), targetCount,
                   detector.angleDeg(), detector.moving() ? "true" : "false", v.hrValid ? v.heartRate : 0,
                   v.spo2Valid ? v.spo2 : 0, v.contact ? "true" : "false",
                   (laptopAlert || bandAlert) ? "true" : "false", accel.clipped() ? "true" : "false", battery);
    }

    updateLedMode();
    led.update(now);
}
