# healthcare_wristband

Wristband that helps track patients' physical rehabilitation exercises and logs them in a
database. ECE 198, team GMI. Together with the computer-vision coach (built separately), this
is **THE MAN-GO: Computer Vision & Wristband Exercise Coach** for CCCARE.

The band counts reps (and range of motion) for the exercises in the "wrist IMU" list, measures
heart rate and SpO2, and flashes a STOP light if the patient is overdoing it. The laptop app runs
the prescribed session, logs everything to a JSON database, shows a live dashboard and suggests
progression or regression for the kinesiologist to approve.

```
firmware/wristband/   ESP32 Arduino sketch (MMA7361 + MAX30102, rep detection, USB/Wi-Fi)
firmware/test/        PC unit tests for the rep detector (g++)
host/wristband/       Python laptop app: band link, sessions, safety, dosage, database, dashboard
host/tests/           pytest suite (includes an end-to-end run against a simulated band)
shared/exercises.json all exercises + detection settings (firmware table is generated from it)
hardware/wiring.md    breadboard wiring, battery, first power-up checklist
docs/design.md        how it works and why
docs/protocol.md      band messages, REST API, computer-vision integration
data/                 example patient; your database.json is created here (git-ignored)
tools/                gen_exercise_table.py
```

## Quick start (no hardware)

```bash
cd host
pip install -r requirements.txt
python -m wristband run --simulate
```

The dashboard opens at http://localhost:8000. Pick **Example Patient** and press
**Start session**. The simulated band counts the wrist exercises. Camera exercises wait for the CV
coach (`POST /api/cv`), or you can type a count. Use `--speed 5` for a faster demo.

## With the wristband

1. **Wire it** following [hardware/wiring.md](hardware/wiring.md).
2. **Flash the firmware** with the Arduino IDE:
   - Boards Manager → install **esp32 by Espressif Systems**, then select board **ESP32 Dev Module**.
   - Library Manager → install **DFRobot_MAX30102**.
   - Open `firmware/wristband/wristband.ino` and click Upload.
3. **Calibrate once:** lay the band flat, face up, and hold the **BOOT** button for 2 s.
4. **Run the app:**
   ```bash
   cd host
   python -m wristband ports            # find the ESP32's port, e.g. COM3
   python -m wristband run --port COM3
   ```
5. **Optional Wi-Fi:** copy `firmware/wristband/secrets.example.h` to `secrets.h`, fill in
   your network and laptop IP, re-upload, then run `python -m wristband run --udp`.

Other commands:

- `python -m wristband monitor --port COM3`: print what the band sends and type commands.
  Add `--raw-csv data.csv` to record raw acceleration for tuning thresholds.
- `python -m wristband report --patient P001`: session history in the terminal.

## How reps are counted

The MMA7361 is an accelerometer only (no gyroscope), so each exercise uses one of three methods
(set in `shared/exercises.json`):

| Mode | Used for | How |
|---|---|---|
| tilt | curls, raises, flies, swings, arm rainbows | Angle from the start position. A rep goes start → top angle → back. Range of motion is reported for every rep, and reps that fall short count as *partial*. |
| motion | presses, squats, lunges, rows, rotations, carries | Acceleration cycles (one push and one pull = one rep). Carries count steps. |
| hold | wall sits | Seconds held still |

To tune an exercise, edit `shared/exercises.json`, then run `python tools/gen_exercise_table.py`
and re-upload. A clinician can also set a per-patient `top_deg` in the prescription.

## Safety and dosage

- Target heart-rate zone: 40-70 % of heart-rate reserve, with max HR from age (Tanaka) or set by
  the clinician. Above the zone gives a warning. Above the stop limit, or SpO2 < 90 %, gives
  **STOP**: the set ends, the LED flashes fast and the instructor must clear it. The band also
  enforces `hr_max` on its own if the laptop link drops. For patients on beta-blockers, HR-zone
  warnings are turned off and the RPE rating is used instead.
- After a session, enter the RPE (Borg 6-20). Each exercise gets a *progress / keep / regress*
  suggestion with reasons. Nothing changes until the clinician ticks and accepts it.

These are screening aids for the instructor, not medical decisions.

## Tests

```bash
make -C firmware/test            # rep detector + JSON helper (needs g++)
cd host && python -m pytest      # laptop app, API, simulator end-to-end
```

## Computer vision

The CV coach reads `GET /api/state` to see which exercise is on and posts its counts and form
scores to `POST /api/cv`. See [docs/protocol.md](docs/protocol.md#computer-vision-integration).

## Credits

The accelerometer code builds on Vic's MMA7361 sketch (`accelerometer_3axis.ino`) and Vraj's
bicep-curl rep counter and `save_data.py` JSON logger (`ACCELEROMETER` branch). The pulse
oximeter code builds on Gloria's MAX30102 sketch (`pulse-oximeter` branch).
