# Protocols

1. [Band ↔ laptop](#band--laptop): one JSON object per line, over USB serial (115200 baud) or Wi-Fi UDP
2. [Laptop REST API](#rest-api), used by the dashboard
3. [Computer-vision integration](#computer-vision-integration), for the CV coach teammate

Exercise IDs everywhere come from [`shared/exercises.json`](../shared/exercises.json).

---

## Band ↔ laptop

**Wi-Fi:** the band sends UDP datagrams to `HOST_IP:5005`. The laptop learns the band's address
from them and sends commands back to `band:5006`. The message format is the same as serial.

### Commands (laptop → band)

| Command | Example | Effect |
|---|---|---|
| `start` | `{"cmd":"start","exercise":"bicep_curl","set":1,"target":12,"hr_max":140,"top_deg":60}` | Starts counting a set. `top_deg` (tilt exercises) and `threshold` (motion, m/s²) override the defaults. `hr_max` turns on band-side HR alerts. |
| `stop` | `{"cmd":"stop"}` | Ends the set and replies `set_done`. |
| `calibrate` | `{"cmd":"calibrate"}` | Zero-g calibration. The band must be flat, face up and still. Saved to flash. |
| `alert` | `{"cmd":"alert","level":"stop"}` | `stop` = fast-flash LED, `warn` = 2 flashes, `none` = clear. |
| `raw` | `{"cmd":"raw","on":true}` | Streams raw acceleration at 50 Hz (for tuning thresholds). |
| `ping` | `{"cmd":"ping"}` | Replies `hello`. |
| `list` | `{"cmd":"list"}` | Replies with the exercise IDs the band can count. |

### Messages (band → laptop)

| `type` | Fields | When |
|---|---|---|
| `hello` | `device, fw, accel, range_g, calibrated, offsets_mv, pulse, wifi, exercises` | Boot and `ping` |
| `started` | `exercise, set, target, unit` | After `start` |
| `ready` | `exercise, set` | Start position captured. The patient can begin. |
| `rep` | `exercise, set, rep, duration_ms, rom_deg, peak_accel, t` | Each completed rep. `rom_deg` = range of motion (tilt exercises). |
| `target_reached` | `exercise, set, count` | Count reached the target. The laptop then sends `stop`. |
| `set_done` | `exercise, set, unit, count, partial, target, duration_ms, active_ms, avg_rep_ms, avg_rom_deg, peak_accel` | After `stop` |
| `vitals` | `hr, spo2, hr_valid, spo2_valid, contact, moving, t` | Every ~4 s with skin contact (~1 s without) |
| `status` | `t, state, exercise, set, count, partial, target, angle, moving, hr, spo2, contact, alert, clipped, battery_v` | Twice per second |
| `alert` | `level, reason, hr, hr_max` | Band-side HR limit exceeded / recovered |
| `calibrated` | `offsets_mv` | Calibration succeeded |
| `raw` | `t, ax, ay, az` (m/s²) | Raw mode only |
| `error`, `log` | `msg` | Problems / information |

`unit` is `reps`, `steps` (carries) or `seconds` (wall sit). `partial` counts tilt reps that
started but never reached the target range of motion.

---

## REST API

Served by `python -m wristband run` at `http://localhost:8000`. All bodies are JSON.

| Method & path | Body | Returns |
|---|---|---|
| `GET /api/state` | | Live state: phase, current step, count, vitals, alert, plan, band |
| `GET /api/catalog` | | Categories and exercises |
| `GET /api/patients` | | All patients |
| `GET /api/patients/<id>` | | Patient with HR limits and prescription warnings |
| `POST /api/patients` | `{id, name, age, resting_hr, hr_max?, hr_stop?, beta_blocker?, prescription?}` | Created/updated patient |
| `POST /api/patients/<id>/prescription` | `{exercises:[{exercise, sets, target, rest_s, top_deg?}]}` **or** `{accept:[exercise ids], session_id}` | Updated patient (old prescription kept in history) |
| `GET /api/sessions?patient=<id>` | | Session summaries |
| `GET /api/sessions/<id>` | | Full session record |
| `POST /api/session/start` | `{patient_id}` | Live state |
| `POST /api/session/end` | `{status?}` | Live state |
| `POST /api/set/start` · `/api/set/stop` · `/api/set/skip` | | Live state |
| `POST /api/set/complete` | `{count}` | Records a manual count for the current set |
| `POST /api/alert/clear` | | Instructor clears a STOP |
| `POST /api/rpe` | `{rpe}` (Borg 6-20) | Live state, with suggestions recomputed |
| `POST /api/cv` | see below | `{matched_current_set, current_exercise}` |
| `POST /api/band/calibrate` · `/api/band/ping` | | `{sent}` |

Errors return `{"error": "..."}` with status 400 (bad input), 404 or 409 (wrong state, e.g. no session).

---

## Computer-vision integration

The CV coach doesn't need to know anything about the band. It does two things:

**1. Find out which exercise is on:** poll `GET /api/state` and read `step.exercise`,
`step.tracker`, `step.target` and `phase`. If `tracker` is `"camera"`, the CV coach is the
counter for this set. If it is `"wrist"`, the band counts and CV results are stored as a
cross-check plus form feedback.

**2. Post results:** `POST /api/cv` as often as you like (e.g. on every rep):

```json
{
  "exercise": "push_up",
  "event": "rep",
  "reps": 7,
  "form_score": 0.82,
  "rom_deg": 75,
  "feedback": "keep your hips in line"
}
```

| Field | Required | Meaning |
|---|---|---|
| `exercise` | yes | ID from `shared/exercises.json` |
| `event` | no | `rep`, `form` or `set_done`. `set_done` ends a camera set even below target. |
| `reps` | no | **Cumulative** reps in this set (seconds for timed holds such as planks) |
| `form_score` | no | 0-1. Averaged per set and stored. |
| `rom_deg` | no | Range of motion for the rep |
| `feedback` | no | Short text shown in the record (last 5 kept per set) |

For camera exercises, the set finishes when `reps` reaches the target or on `set_done`. Every
event is also stored in the session's `cv_events`. The CORS header `*` is sent, so a
browser-based CV app on another port can post directly. If the CV coach runs on a different
computer, start the app with `--host 0.0.0.0`.

Python example:

```python
import requests
state = requests.get("http://localhost:8000/api/state").json()
if state["step"] and state["step"]["exercise"] == "push_up":
    requests.post("http://localhost:8000/api/cv", json={"exercise": "push_up", "reps": 3, "form_score": 0.9})
```
