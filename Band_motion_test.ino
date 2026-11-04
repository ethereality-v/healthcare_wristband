
/*
  HEALTH BAND - MMA7361 + ESP32

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

// ---------- PINS ----------

const int PIN_X       = 34;
const int PIN_Y       = 35;
const int PIN_Z       = 32;
const int PIN_SLEEP   = 25;
const int PIN_GSELECT = 26;

// ---------- SENSOR CONSTANTS ----------

const float SENSITIVITY_MV_PER_G = 206.0;
const float GRAVITY = 9.80665;

// ---------- SAMPLING ----------

const unsigned long SAMPLE_INTERVAL_MS = 20;
const int OVERSAMPLE = 8;
const int CALIBRATION_SAMPLES = 200;

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

    selectedAngle = 0;

    float pitch = atan2(
        -ax,
        sqrt(ay * ay + az * az)
    ) * 180.0 / PI;

    float roll = atan2(
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

    double pitchSum = 0;
    double rollSum = 0;

    for (int i = 0; i < 100; i++) {

        readAcceleration();

        float pitch = atan2(
            -ax,
            sqrt(ay * ay + az * az)
        ) * 180.0 / PI;

        float roll = atan2(
            ay, az
        ) * 180.0 / PI;

        pitchSum += pitch;
        rollSum += roll;

        delay(20);
    }

    startingPitch = pitchSum / 100.0;
    startingRoll = rollSum / 100.0;

    if (REP_ANGLE_AXIS == 0) {
        startingAngle = startingPitch;
    }
    else {
        startingAngle = startingRoll;
    }

    Serial.printf(
        "# Starting pitch: %.1f degrees\n",
        startingPitch
    );

    Serial.printf(
        "# Starting roll: %.1f degrees\n",
        startingRoll
    );
}

// ---------- REPETITION COUNTER ----------

void calculateRepetitions() {

    unsigned long now = millis();

    // Calculate difference from the starting position

    angleDifference = fabs(
        selectedAngle - startingAngle
    );

    // Check whether the band is moving

    movementActive =
        angleDifference > REP_START_DEG;

    // STEP 1: Detect the beginning of a repetition

    if (!repInProgress && movementActive) {

        repInProgress = true;
        reachedTop = false;

        repStartTime = now;

        currentRepPeakAcceleration = magnitude;
    }

    // STEP 2: Track peak acceleration during the rep

    if (repInProgress) {

        if (magnitude > currentRepPeakAcceleration) {
            currentRepPeakAcceleration = magnitude;
        }
    }

    // STEP 3: Detect the top of the movement

    if (
        repInProgress &&
        angleDifference >= REP_TOP_DEG
    ) {

        reachedTop = true;
    }

    // STEP 4: Detect return to starting position

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

        // Reset for the next repetition

        repInProgress = false;
        reachedTop = false;
    }
}

// ---------- SETUP ----------

void setup() {

    Serial.begin(115200);

    delay(500);

    pinMode(PIN_SLEEP, OUTPUT);
    digitalWrite(PIN_SLEEP, HIGH);

    pinMode(PIN_GSELECT, OUTPUT);
    digitalWrite(PIN_GSELECT, HIGH);

    delay(10);

    analogReadResolution(12);
    analogSetAttenuation(ADC_11db);

    if (!sensorLooksConnected()) {

        Serial.println(
            "# MMA7361 not responding! Check wiring."
        );

        while (1) {
            delay(10);
        }
    }

    calibrate();

    calibrateStartingPosition();

    sessionStartTime = millis();

    Serial.println("# Health Band Started!");
    Serial.println("# Exercise session started!");

    // CSV HEADER

    Serial.println(
        "time_ms,session_seconds,ax,ay,az,"
        "magnitude,pitch_deg,roll_deg,"
        "repetitions,rep_event,last_rep_duration_ms,"
        "average_rep_duration_ms,peak_acceleration,"
        "movement_status"
    );
}

// ---------- MAIN LOOP ----------

void loop() {

    unsigned long now = millis();

    if (now - lastSampleTime >= SAMPLE_INTERVAL_MS) {

        lastSampleTime = now;

        // Read acceleration

        readAcceleration();

        // Calculate angles

        calculateAngles();

        float pitch = atan2(
            -ax,
            sqrt(ay * ay + az * az)
        ) * 180.0 / PI;

        float roll = atan2(
            ay, az
        ) * 180.0 / PI;

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

        // CSV OUTPUT

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
            Serial.println("ACTIVE");
        }
        else {
            Serial.println("RESTING");
        }
    }
}
