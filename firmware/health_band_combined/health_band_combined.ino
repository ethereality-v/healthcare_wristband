/*
  HEALTH BAND - MMA7361 + MAX30102 ON ONE ESP32

  Runs the accelerometer rep counter and the pulse oximeter
  together on a single ESP32 DevKit (30 pins, ESP32-WROOM-32).

  FEATURES
  - X, Y, Z acceleration
  - Acceleration magnitude
  - Pitch and roll
  - Repetition counter
  - Exercise session duration
  - Duration of each repetition
  - Average repetition duration
  - Peak acceleration
  - Movement status
  - Heart rate and SpO2 (MAX30102)
  - 50 Hz JSON sensor samples over Bluetooth Classic SPP

  WIRING (pin names as printed on the board)
    MMA7361 X            -> D34
    MMA7361 Y            -> D35
    MMA7361 Z            -> D32
    MMA7361 SL           -> D25
    MMA7361 GS           -> D26
    MMA7361 3V3 (or VCC) -> breadboard + rail
    MMA7361 GND          -> breadboard - rail
    MAX30102 SDA         -> D21
    MAX30102 SCL         -> D22
    MAX30102 VIN         -> breadboard + rail
    MAX30102 GND         -> breadboard - rail
    ESP32 3V3            -> breadboard + rail
    ESP32 GND            -> breadboard - rail
    MMA7361 0G, ST and MAX30102 INT are not connected.

  The board has only one 3V3 pin, so both sensors share it
  through the breadboard's + rail.

  LIBRARY
  Install DFRobot_MAX30102 from the Arduino Library Manager
  (the same library as the pulse oximeter code).

  HOW BOTH SENSORS SHARE ONE ESP32
  The ESP32 has two processor cores. Measuring heart rate
  blocks for about 4 seconds while the MAX30102 collects
  100 samples, so it runs in its own task on core 0.
  The accelerometer and rep counter run in loop() on core 1
  and keep sampling at 50 Hz, so no reps are missed.

  IMPORTANT:
  This version uses the MMA7361 analog accelerometer.
  It does NOT use the GY-521 / MPU6050.

  REP COUNTING:
  1. Hold the band in your exercise starting position.
  2. Move until the selected angle changes by REP_TOP_DEG.
  3. Return close to the starting angle.
  4. One complete cycle is counted.
*/

#include <Arduino.h>
#include <math.h>
#include <Wire.h>
#include <DFRobot_MAX30102.h>
#include <BluetoothSerial.h>

// ---------- PINS ----------

// MMA7361 accelerometer (analog).
// X, Y and Z must use ADC1 pins (D32-D39) because
// ADC2 pins stop working when Wi-Fi is on.

const int PIN_X       = 34;   // D34
const int PIN_Y       = 35;   // D35
const int PIN_Z       = 32;   // D32
const int PIN_SLEEP   = 25;   // D25
const int PIN_GSELECT = 26;   // D26

// MAX30102 pulse oximeter (I2C, the ESP32's default I2C pins)

const int PIN_I2C_SDA = 21;   // D21
const int PIN_I2C_SCL = 22;   // D22

// ---------- SENSOR CONSTANTS ----------

// GS is set HIGH in setup(): +/-6 g range, 206 mV per g

const float SENSITIVITY_MV_PER_G = 206.0;
const float GRAVITY = 9.80665;

// ---------- SAMPLING ----------

const unsigned long SAMPLE_INTERVAL_MS = 20;
const int OVERSAMPLE = 8;
const int CALIBRATION_SAMPLES = 200;

// ---------- OUTPUT ----------

// 0 = CSV line every 1.5 seconds (Serial Monitor, Serial Plotter, testing)
// 1 = JSON line every second (for save_data.py)
//
// Opening the port from save_data.py usually restarts the ESP32,
// so lay the band flat for calibration when you start it.

const int OUTPUT_FORMAT = 0;

const unsigned long JSON_INTERVAL_MS = 1000;

// The sensor is still read every 20 ms (the rep counter needs that),
// but only every Nth reading is printed as a CSV line:
// N = 1500 ms / 20 ms = 75, so one line every 1.5 seconds.
// Set to 1 to print every reading again.

const int CSV_PRINT_EVERY = 75;

// ---------- SENSOR CALIBRATION ----------

float zeroX = 1650.0;
float zeroY = 1650.0;
float zeroZ = 1650.0;

// ---------- REPETITION SETTINGS ----------

// 0 = pitch
// 1 = roll
//
// We will determine the correct axis by testing
// the sensor during your exercise.

const int REP_ANGLE_AXIS = 0;

// Angle thresholds relative to starting position

const float REP_START_DEG = 8.0;
const float REP_TOP_DEG = 35.0;
const float REP_RETURN_DEG = 12.0;

// Timing thresholds

const unsigned long MIN_REP_TIME = 400;
const unsigned long MIN_REP_INTERVAL = 500;

// ---------- PULSE OXIMETER SETTINGS ----------

const int PULSE_LED_BRIGHTNESS = 60;   // 0-255

// Readings outside these ranges come from motion
// or poor skin contact, so they are ignored.

const int MIN_HEART_RATE = 35;
const int MAX_HEART_RATE = 220;
const int MIN_SPO2 = 70;

// If no new measurement arrives for this long (for example
// a loose wire), heart rate and SpO2 are reported as missing
// instead of repeating an old value.

const unsigned long VITALS_TIMEOUT_MS = 10000;

// ---------- EXERCISE VARIABLES ----------

int repetitions = 0;

bool repInProgress = false;
bool reachedTop = false;

unsigned long sessionStartTime = 0;
unsigned long repStartTime = 0;
unsigned long lastRepTime = 0;

unsigned long totalRepDuration = 0;
unsigned long lastRepDuration = 0;

float averageRepDuration = 0;

// ---------- ANGLE VARIABLES ----------

float pitch = 0;
float roll = 0;

float startingPitch = 0;
float startingRoll = 0;

float selectedAngle = 0;
float startingAngle = 0;
float angleDifference = 0;

// ---------- ACCELERATION VARIABLES ----------

float ax = 0;
float ay = 0;
float az = 0;

float magnitude = 0;

float peakAcceleration = 0;
float currentRepPeakAcceleration = 0;

// ---------- MOVEMENT VARIABLES ----------

bool movementActive = false;

unsigned long lastSampleTime = 0;
unsigned long lastJsonTime = 0;

int readingsSinceCsvLine = 0;
int pendingRepEvent = 0;   // a rep finished since the last printed line

// ---------- PULSE OXIMETER VARIABLES ----------

DFRobot_MAX30102 particleSensor;
BluetoothSerial bluetooth;

bool pulseSensorFound = false;

// Written by the pulse task (core 0) and read by loop() (core 1).
// The lock makes sure loop() never reads a half-updated set.
// A value of 0 means there is no valid reading.

portMUX_TYPE vitalsLock = portMUX_INITIALIZER_UNLOCKED;

int latestHeartRate = 0;              // BPM
int latestSpO2 = 0;                   // %
unsigned long latestVitalsTime = 0;   // millis() of the last measurement

// ---------- READ SENSOR ----------

float readAxisMilliVolts(int pin) {

    uint32_t total = 0;

    for (int i = 0; i < OVERSAMPLE; i++) {
        total += analogReadMilliVolts(pin);
    }

    return (float)total / OVERSAMPLE;
}

// ---------- CHECK SENSOR ----------

bool sensorLooksConnected() {

    float x = readAxisMilliVolts(PIN_X);
    float y = readAxisMilliVolts(PIN_Y);
    float z = readAxisMilliVolts(PIN_Z);

    bool ok = true;

    if (x < 500 || x > 2800) ok = false;
    if (y < 500 || y > 2800) ok = false;
    if (z < 500 || z > 2800) ok = false;

    Serial.printf(
        "# Raw check (mV): X=%.0f Y=%.0f Z=%.0f\n",
        x, y, z
    );

    return ok;
}

// ---------- CALIBRATION ----------

void calibrate() {

    Serial.println(
        "# Calibration: place the sensor flat, face up and still."
    );

    delay(2000);

    double sumX = 0;
    double sumY = 0;
    double sumZ = 0;

    for (int i = 0; i < CALIBRATION_SAMPLES; i++) {

        sumX += readAxisMilliVolts(PIN_X);
        sumY += readAxisMilliVolts(PIN_Y);
        sumZ += readAxisMilliVolts(PIN_Z);

        delay(5);
    }

    zeroX = sumX / CALIBRATION_SAMPLES;
    zeroY = sumY / CALIBRATION_SAMPLES;

    zeroZ =
        (sumZ / CALIBRATION_SAMPLES)
        - SENSITIVITY_MV_PER_G;

    Serial.printf(
        "# Zero offsets: X=%.1f Y=%.1f Z=%.1f mV\n",
        zeroX, zeroY, zeroZ
    );

    if (
        fabs(zeroX - 1650) > 250 ||
        fabs(zeroY - 1650) > 250 ||
        fabs(zeroZ - 1650) > 250
    ) {
        Serial.println(
            "# Warning: calibration offsets look unusual."
        );
    }
}

// ---------- CONVERT VOLTAGE TO ACCELERATION ----------

float toMetersPerSecondSquared(
    float milliVolts,
    float zeroG
) {

    return (
        (milliVolts - zeroG)
        / SENSITIVITY_MV_PER_G
    ) * GRAVITY;
}

// ---------- CALCULATE ACCELERATION ----------

void readAcceleration() {

    ax = toMetersPerSecondSquared(
        readAxisMilliVolts(PIN_X), zeroX
    );

    ay = toMetersPerSecondSquared(
        readAxisMilliVolts(PIN_Y), zeroY
    );

    az = toMetersPerSecondSquared(
        readAxisMilliVolts(PIN_Z), zeroZ
    );

    // Combined acceleration across all three axes

    magnitude = sqrt(
        ax * ax +
        ay * ay +
        az * az
    );

    // Track the highest acceleration during the session

    if (magnitude > peakAcceleration) {
        peakAcceleration = magnitude;
    }
}

// ---------- CALCULATE PITCH AND ROLL ----------

void calculateAngles() {

    pitch = atan2(
        -ax,
        sqrt(ay * ay + az * az)
    ) * 180.0 / PI;

    roll = atan2(
        ay, az
    ) * 180.0 / PI;

    // Select the axis used for repetition counting

    if (REP_ANGLE_AXIS == 0) {
        selectedAngle = pitch;
    }
    else {
        selectedAngle = roll;
    }
}

// ---------- CALIBRATE EXERCISE STARTING POSITION ----------

void calibrateStartingPosition() {

    Serial.println(
        "# Hold the band in your exercise starting position."
    );

    Serial.println(
        "# Keep your arm still while the starting angle is measured."
    );

    delay(3000);

    // Average the acceleration first, then calculate the angles once.
    // (Averaging roll angles directly gives a wrong result near
    // +/-180 degrees, where 179 and -179 would average to 0.)

    double sumX = 0;
    double sumY = 0;
    double sumZ = 0;

    for (int i = 0; i < 100; i++) {

        readAcceleration();

        sumX += ax;
        sumY += ay;
        sumZ += az;

        delay(20);
    }

    ax = sumX / 100.0;
    ay = sumY / 100.0;
    az = sumZ / 100.0;

    calculateAngles();

    startingPitch = pitch;
    startingRoll = roll;
    startingAngle = selectedAngle;

    Serial.printf(
        "# Starting pitch: %.1f degrees\n",
        startingPitch
    );

    Serial.printf(
        "# Starting roll: %.1f degrees\n",
        startingRoll
    );
}

// ---------- PULSE OXIMETER TASK (RUNS ON CORE 0) ----------

void pulseTask(void *parameter) {

    for (;;) {

        int32_t measuredSpO2 = 0;
        int8_t  spo2Valid = 0;
        int32_t measuredHeartRate = 0;
        int8_t  heartRateValid = 0;

        // Collects 100 samples, then calculates heart rate and SpO2.
        // This takes about 4 seconds.

        particleSensor.heartrateAndOxygenSaturation(
            &measuredSpO2, &spo2Valid,
            &measuredHeartRate, &heartRateValid
        );

        // Keep only valid, realistic readings (0 = no reading)

        int heartRate = 0;
        int spo2 = 0;

        if (
            heartRateValid &&
            measuredHeartRate >= MIN_HEART_RATE &&
            measuredHeartRate <= MAX_HEART_RATE
        ) {
            heartRate = measuredHeartRate;
        }

        if (
            spo2Valid &&
            measuredSpO2 >= MIN_SPO2 &&
            measuredSpO2 <= 100
        ) {
            spo2 = measuredSpO2;
        }

        // Share the new values with loop()

        portENTER_CRITICAL(&vitalsLock);
        latestHeartRate = heartRate;
        latestSpO2 = spo2;
        latestVitalsTime = millis();
        portEXIT_CRITICAL(&vitalsLock);

        // Let other tasks on core 0 run for a moment

        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

// ---------- SET UP PULSE OXIMETER ----------

void setupPulseSensor() {

    Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);

    // Try a few times: the module can need a moment after power-up.
    // If it is missing, the rep counter still runs without it.

    for (int attempt = 0; attempt < 3; attempt++) {

        if (particleSensor.begin()) {
            pulseSensorFound = true;
            break;
        }

        delay(500);
    }

    if (!pulseSensorFound) {

        Serial.println(
            "# MAX30102 not found! Check SDA (D21), SCL (D22), VIN and GND."
        );

        Serial.println(
            "# Continuing without heart rate and SpO2."
        );

        return;
    }

    // Same settings as the pulse oximeter code

    particleSensor.sensorConfiguration(
        PULSE_LED_BRIGHTNESS,
        SAMPLEAVG_4,      // average 4 samples
        MODE_MULTILED,    // red + IR (needed for SpO2)
        SAMPLERATE_100,   // 100 samples per second
        PULSEWIDTH_411,   // 18-bit resolution
        ADCRANGE_16384    // ADC range
    );

    // Run the pulse oximeter on core 0. loop() runs on core 1.

    xTaskCreatePinnedToCore(
        pulseTask,   // function to run
        "pulse",     // task name
        8192,        // stack size in bytes
        NULL,        // parameter (not used)
        1,           // priority
        NULL,        // task handle (not used)
        0            // core
    );

    Serial.println(
        "# MAX30102 found. Keep it pressed against the skin and hold still for readings."
    );
}

// ---------- PRINT REP SUMMARY ----------

void printRepSummary(unsigned long repDuration) {

    Serial.println(
        "# --------------------------"
    );

    Serial.println("# REP COMPLETED");

    Serial.printf(
        "# Total repetitions: %d\n",
        repetitions
    );

    Serial.printf(
        "# Rep duration: %.2f seconds\n",
        repDuration / 1000.0
    );

    Serial.printf(
        "# Average rep duration: %.2f seconds\n",
        averageRepDuration / 1000.0
    );

    Serial.printf(
        "# Peak acceleration in rep: %.2f m/s^2\n",
        currentRepPeakAcceleration
    );

    Serial.println(
        "# --------------------------"
    );
}

// ---------- REPETITION COUNTER ----------

void calculateRepetitions() {

    unsigned long now = millis();

    // Calculate difference from the starting position.
    // Wrap it to -180..180 so roll does not jump from
    // +179 to -179 and look like a 358 degree movement.

    float difference = selectedAngle - startingAngle;

    if (difference > 180.0) {
        difference -= 360.0;
    }

    if (difference < -180.0) {
        difference += 360.0;
    }

    angleDifference = fabs(difference);

    // Check whether the band is away from the starting position

    movementActive =
        angleDifference > REP_START_DEG;

    // STEP 1: Detect the beginning of a repetition

    if (!repInProgress && movementActive) {

        repInProgress = true;
        reachedTop = false;

        repStartTime = now;

        currentRepPeakAcceleration = magnitude;
    }

    // STEP 2: Cancel a rep that came back to the start without
    // reaching the top (for example, shifting your arm between reps).
    // Otherwise the next real rep would keep this rep's start time.

    if (repInProgress && !reachedTop && !movementActive) {

        repInProgress = false;
    }

    // STEP 3: Track peak acceleration during the rep

    if (repInProgress) {

        if (magnitude > currentRepPeakAcceleration) {
            currentRepPeakAcceleration = magnitude;
        }
    }

    // STEP 4: Detect the top of the movement

    if (
        repInProgress &&
        angleDifference >= REP_TOP_DEG
    ) {

        reachedTop = true;
    }

    // STEP 5: Detect return to starting position

    if (
        repInProgress &&
        reachedTop &&
        angleDifference <= REP_RETURN_DEG
    ) {

        unsigned long repDuration = now - repStartTime;

        // Count only movements that last long enough
        // and are separated by a minimum interval.

        if (
            repDuration >= MIN_REP_TIME &&
            now - lastRepTime >= MIN_REP_INTERVAL
        ) {

            repetitions++;

            lastRepDuration = repDuration;

            totalRepDuration += repDuration;

            averageRepDuration =
                (float)totalRepDuration / repetitions;

            lastRepTime = now;

            if (OUTPUT_FORMAT == 0) {
                printRepSummary(repDuration);
            }
        }

        // Reset for the next repetition

        repInProgress = false;
        reachedTop = false;
    }
}

// ---------- OUTPUT ----------

// One CSV line per sample. Heart rate and SpO2 are left
// blank when there is no valid reading.

void printCsvLine(
    unsigned long now,
    unsigned long sessionDuration,
    int repEvent,
    int heartRate,
    int spo2
) {

    Serial.print(now);
    Serial.print(",");

    Serial.print(sessionDuration / 1000.0, 2);
    Serial.print(",");

    Serial.print(ax, 3);
    Serial.print(",");

    Serial.print(ay, 3);
    Serial.print(",");

    Serial.print(az, 3);
    Serial.print(",");

    Serial.print(magnitude, 3);
    Serial.print(",");

    Serial.print(pitch, 1);
    Serial.print(",");

    Serial.print(roll, 1);
    Serial.print(",");

    Serial.print(repetitions);
    Serial.print(",");

    Serial.print(repEvent);
    Serial.print(",");

    Serial.print(lastRepDuration);
    Serial.print(",");

    Serial.print(averageRepDuration, 1);
    Serial.print(",");

    Serial.print(peakAcceleration, 3);
    Serial.print(",");

    if (movementActive) {
        Serial.print("ACTIVE");
    }
    else {
        Serial.print("RESTING");
    }
    Serial.print(",");

    if (heartRate > 0) {
        Serial.print(heartRate);
    }
    Serial.print(",");

    if (spo2 > 0) {
        Serial.print(spo2);
    }
    Serial.println();
}

// Prints a heart rate or SpO2 value, or null if there is no valid reading

void printJsonReading(int value) {

    if (value > 0) {
        Serial.print(value);
    }
    else {
        Serial.print("null");
    }
}

// One JSON line with the keys save_data.py reads
// (reps, heart_rate, spo2) plus the other session values

void printJsonLine(
    unsigned long sessionDuration,
    int heartRate,
    int spo2
) {

    Serial.print("{\"reps\":");
    Serial.print(repetitions);

    Serial.print(",\"heart_rate\":");
    printJsonReading(heartRate);

    Serial.print(",\"spo2\":");
    printJsonReading(spo2);

    Serial.print(",\"session_seconds\":");
    Serial.print(sessionDuration / 1000.0, 2);

    Serial.print(",\"last_rep_duration_ms\":");
    Serial.print(lastRepDuration);

    Serial.print(",\"average_rep_duration_ms\":");
    Serial.print(averageRepDuration, 1);

    Serial.print(",\"peak_acceleration\":");
    Serial.print(peakAcceleration, 3);

    Serial.print(",\"movement_status\":\"");

    if (movementActive) {
        Serial.print("ACTIVE");
    }
    else {
        Serial.print("RESTING");
    }

    Serial.println("\"}");
}

void printBluetoothSample(
    unsigned long now,
    unsigned long sessionDuration,
    int repEvent,
    int heartRate,
    int spo2
) {
    if (!bluetooth.hasClient()) return;

    char heartRateText[8];
    char spo2Text[8];
    if (heartRate > 0) snprintf(heartRateText, sizeof(heartRateText), "%d", heartRate);
    else snprintf(heartRateText, sizeof(heartRateText), "null");
    if (spo2 > 0) snprintf(spo2Text, sizeof(spo2Text), "%d", spo2);
    else snprintf(spo2Text, sizeof(spo2Text), "null");

    char line[320];
    snprintf(line, sizeof(line),
        "{\"type\":\"sample\",\"t\":%lu,\"session_seconds\":%.2f,"
        "\"ax\":%.3f,\"ay\":%.3f,\"az\":%.3f,\"magnitude\":%.3f,"
        "\"pitch_deg\":%.1f,\"roll_deg\":%.1f,\"repetitions\":%d,\"rep_event\":%d,"
        "\"last_rep_duration_ms\":%lu,\"average_rep_duration_ms\":%.1f,"
        "\"peak_acceleration\":%.3f,\"movement_status\":\"%s\","
        "\"heart_rate\":%s,\"spo2\":%s}",
        now, sessionDuration / 1000.0, ax, ay, az, magnitude, pitch, roll, repetitions, repEvent,
        lastRepDuration, averageRepDuration, peakAcceleration, movementActive ? "ACTIVE" : "RESTING",
        heartRateText, spo2Text);
    bluetooth.println(line);
}

// ---------- SETUP ----------

void setup() {

    Serial.begin(115200);

    delay(500);

    uint64_t mac = ESP.getEfuseMac();
    char bluetoothName[24];
    snprintf(bluetoothName, sizeof(bluetoothName), "HealthBand-%04X", (unsigned)((mac >> 32) & 0xFFFF));
    if (!bluetooth.begin(bluetoothName)) {
        Serial.println("# Bluetooth SPP failed to start.");
    } else {
        Serial.printf("# Bluetooth SPP ready: %s\n", bluetoothName);
    }

    pinMode(PIN_SLEEP, OUTPUT);
    digitalWrite(PIN_SLEEP, HIGH);

    pinMode(PIN_GSELECT, OUTPUT);
    digitalWrite(PIN_GSELECT, HIGH);

    delay(10);

    analogReadResolution(12);
    analogSetAttenuation(ADC_11db);

    if (!sensorLooksConnected()) {

        Serial.println(
            "# MMA7361 not responding! Check X (D34), Y (D35), Z (D32), SL (D25), 3V3 and GND."
        );

        while (1) {
            delay(10);
        }
    }

    // Start the pulse oximeter first so its first reading
    // is ready by the time calibration finishes

    setupPulseSensor();

    calibrate();

    calibrateStartingPosition();

    // Bumps during setup should not count as the session's peak

    peakAcceleration = 0;

    sessionStartTime = millis();

    Serial.println("# Health Band Started!");
    Serial.println("# Exercise session started!");

    // CSV HEADER

    if (OUTPUT_FORMAT == 0) {

        Serial.println(
            "time_ms,session_seconds,ax,ay,az,"
            "magnitude,pitch_deg,roll_deg,"
            "repetitions,rep_event,last_rep_duration_ms,"
            "average_rep_duration_ms,peak_acceleration,"
            "movement_status,heart_rate_bpm,spo2_percent"
        );
    }
}

// ---------- MAIN LOOP ----------

void loop() {

    unsigned long now = millis();

    if (now - lastSampleTime >= SAMPLE_INTERVAL_MS) {

        lastSampleTime = now;

        // Read acceleration and calculate angles

        readAcceleration();

        calculateAngles();

        // Detect repetitions

        int previousReps = repetitions;

        calculateRepetitions();

        // Identify whether a repetition was just completed

        int repEvent = 0;

        if (repetitions > previousReps) {
            repEvent = 1;
        }

        // Calculate session duration

        unsigned long sessionDuration =
            millis() - sessionStartTime;

        // Copy the latest heart rate and SpO2 from the pulse task

        portENTER_CRITICAL(&vitalsLock);
        int heartRate = latestHeartRate;
        int spo2 = latestSpO2;
        unsigned long vitalsTime = latestVitalsTime;
        portEXIT_CRITICAL(&vitalsLock);

        // Report old readings as missing

        if (millis() - vitalsTime > VITALS_TIMEOUT_MS) {
            heartRate = 0;
            spo2 = 0;
        }

        printBluetoothSample(now, sessionDuration, repEvent, heartRate, spo2);

        // Output

        if (OUTPUT_FORMAT == 0) {

            // Remember a rep that finishes between printed lines,
            // so rep_event is 1 on the next line that is printed

            if (repEvent == 1) {
                pendingRepEvent = 1;
            }

            readingsSinceCsvLine++;

            if (readingsSinceCsvLine >= CSV_PRINT_EVERY) {

                readingsSinceCsvLine = 0;

                printCsvLine(
                    now, sessionDuration, pendingRepEvent, heartRate, spo2
                );

                pendingRepEvent = 0;
            }
        }
        else if (now - lastJsonTime >= JSON_INTERVAL_MS) {

            lastJsonTime = now;

            printJsonLine(sessionDuration, heartRate, spo2);
        }
    }
}
