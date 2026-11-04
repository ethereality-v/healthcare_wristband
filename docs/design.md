# Healthcare Wristband: Design

ECE 198 project (team GMI). The wristband plus the computer-vision (CV) coach together make
**THE MAN-GO**. This document covers everything **except** the CV part, which a teammate is
building and which plugs in through the API described in [protocol.md](protocol.md).

## Goal

CCCARE instructors supervise 10-30 participants per session. The wristband checks each
participant automatically and reports to the instructor:

- whether the prescribed exercises were done (reps, sets, hold time, range of motion), and
- whether the participant is in a safe effort zone (heart rate, SpO2), with a stop warning when they are not.

The final decision about dosage always stays with the kinesiologist. The software only *suggests*
progression or regression.

## Hardware: first test (materials list + battery)

| Part | Use |
|---|---|
| ESP32 dev board | Main controller: reads the sensors, counts reps, talks over USB serial or Wi-Fi |
| MMA7361 3-axis analog accelerometer | Wrist motion and tilt (there is no gyroscope) |
| GY-MAX30102 pulse oximeter | Heart rate and SpO2, sensor window against the skin |
| 3.7 V 1S LiPo, ~500 mAh, protected, JST-PH 2.0 (e.g. 502535) | Battery, about 3 h with Wi-Fi on |
| TP4056 USB-C charger module (with protection) | Charges the LiPo safely |
| Breadboard + jumper wires | Wiring for the first test (this repo covers the first test only) |
| 3D printing | Wristband enclosure (CAD designed separately by the team) |
| Arduino UNO R4 Minima | Not used by the band (spare / bench testing) |

The ESP32's onboard LED (GPIO 2) is the band's "light". The BOOT button (GPIO 0) is its only
button. There is no display on the materials list, so the laptop dashboard does the "which
exercise / data" display job.

Wiring, battery and power details are in [../hardware/wiring.md](../hardware/wiring.md).

## Architecture

```
 ┌──────────── Wristband (ESP32) ────────────┐        ┌────────────── Laptop (Python) ──────────────┐
 │ core 1, 50 Hz loop                        │  JSON  │ transport: serial / UDP / simulator         │
 │  MMA7361 ─► RepDetector ─► rep events     │ lines  │ SessionRunner: prescription → sets → reps   │
 │                (tilt / motion / hold)     │◄──────►│ Safety: HR zone, SpO2 → STOP alert          │
 │ core 0, FreeRTOS task                     │ USB or │ Dosage: progress / keep / regress hint      │
 │  MAX30102 ─► HR + SpO2 (every ~4 s)       │ Wi-Fi  │ JSON database  (data/database.json)         │
 │ LED patterns, BOOT-button calibration     │        │ Dashboard + REST API (http://localhost:8000) │
 └───────────────────────────────────────────┘        │   ▲ POST /api/cv  ◄── CV coach (teammate)    │
                                                      └─────────────────────────────────────────────┘
```

### Firmware (`firmware/wristband/`)

- **Two cores.** The DFRobot MAX30102 measurement blocks for about 4 s while it collects 100
  samples. It runs in its own FreeRTOS task on core 0, so accelerometer sampling on core 1 never
  stalls.
- **Calibration is stored in flash** (NVS `Preferences`). To calibrate, place the band flat and
  face up, then hold BOOT for 2 s (or send `{"cmd":"calibrate"}`). After that, the band no longer
  has to lie flat at every boot.
- **±1.5 g range by default** (800 mV/g instead of 206 mV/g). This gives about 4× better
  resolution for slow rehab movements. `ACCEL_RANGE_6G` in `config.h` switches back to ±6 g.
- **Rep detection** (`rep_detector.cpp`, plain C++ and unit-tested on a PC). Each exercise has a
  profile in `shared/exercises.json` that picks one of three modes:
  - **tilt**: the angle between the current gravity direction and the gravity direction captured
    while the patient holds the start position. It works no matter how the band is worn. A rep is
    start → top angle → back to start, and it reports the **range of motion** of every rep. Reps
    that never reach the top angle are counted separately as *partial reps*. Used for curls,
    raises, flies, swings and arm rainbows.
  - **motion**: band-passed linear acceleration (vertical, or the dominant axis) with a hysteresis
    counter. One positive lobe plus one negative lobe makes one rep. This mode is needed because an
    accelerometer alone cannot see rotation about the vertical axis or pure translation. Used for
    presses, squats, lunges, rows, rotations and carries (counts steps).
  - **hold**: seconds spent still (wall sit).
- **Safety on the band itself.** The `start` command carries `hr_max`. If HR goes above it, the
  LED flashes fast even if the laptop link drops.

### Laptop app (`host/wristband/`)

- `transport.py`: serial (USB), UDP (Wi-Fi) or the simulator, all with the same interface.
- `session.py`: walks the patient's prescription. Order: warm-up → 2 mobility → one exercise per
  functional category → stretches → cool-down, with sets × reps (10-20 reps, 1-2 sets).
  Wrist-trackable exercises are sent to the band. Camera-only exercises wait for CV results or a
  manual confirmation.
- `safety.py`: target heart-rate zone from age (Tanaka 208 − 0.7 × age, or a clinician-set
  maximum; beta-blocker aware). Gives a warning near the top of the zone and a **STOP** above it or
  when SpO2 < 90 %. Only plausible readings taken while the wrist is still are trusted.
- `dosage.py`: compares completed vs prescribed reps, RPE, HR zone and ROM, then suggests
  *progress / keep / regress* for each exercise. It is flagged for the clinician and never applied
  automatically.
- `database.py`: one JSON file (patients, prescriptions, sessions, per-rep data, vitals, CV
  results). Writes are atomic so a crash can't corrupt it.
- `server.py`: dashboard + REST API using the Python standard library only.

## Decisions

| Decision | Why |
|---|---|
| USB serial default, Wi-Fi (UDP) optional | USB is the simplest way to debug. Wi-Fi is enabled in `secrets.h` once the battery is in. UDP is bidirectional and needs no extra library. |
| Hand-written JSON on the band, no ArduinoJson | One less library for teammates to install. Messages are small and flat. |
| Exercise table generated from one JSON file | Firmware and laptop can never disagree about exercise IDs or thresholds (`tools/gen_exercise_table.py`, checked by a test). |
| Standard-library-only web server | `pip install pyserial` is the only setup step. |
| Vitals measured best at rest | Wrist PPG is unreliable during movement, so the laptop uses vitals from still periods (between sets). |

## Testing

- `firmware/test`: g++ unit tests for the rep detector (synthetic curls, presses, partial reps,
  holds, noise) and the JSON helper.
- `host/tests`: pytest for safety, dosage, prescriptions, database, session flow, the API and the
  simulator end to end. A test also checks that the generated exercise table matches the JSON.
- `arduino-cli compile` for `esp32:esp32:esp32`.
