# Multi-Exercise AI Tracker

A local Python/OpenCV application that uses MediaPipe Pose Landmarker to count repetitions or time holds from a webcam. Exercise selection is manual, which keeps the tracker predictable and avoids requiring a custom exercise-classification dataset.

## Exercises

| Key | Exercise | Measurement | Recommended camera position |
|---|---|---|---|
| `1` | Standing hip opener / closer | Total and left/right reps | Front, full body |
| `2` | Scapular squeezes | Reps | Front, both arms bent |
| `3` | Lunges | Total and left/right reps | Side or 45 degrees, full body |
| `4` | Push-ups | Reps | Side, full body |
| `5` | Chest press | Reps | 45 degrees, both arms visible |
| `6` | Kettlebell swings | Reps | Side, full body and hands visible |
| `7` | Deadlifts | Reps | Side, full body |
| `8` | Seated row | Reps | Side or 45 degrees, both arms |
| `9` | Lat pulldown | Reps | Front, upper body and hands |
| `A` | Suitcase carry | Valid-posture time | Front, full body |
| `B` | Plank | Valid-position time | Side, full body |
| `C` | Mountain climbers | Total and left/right knee drives | Side or 45 degrees |
| `D` | Hamstring stretch | Valid-position time | Side, full body |
| `E` | Calf stretch | Valid-position time | Side, both feet |
| `F` | Step-ups | Total and left/right reps | Side or 45 degrees, step visible |

## Requirements

- Python 3.10, 3.11, or 3.12 is recommended.
- A webcam.
- Even lighting and enough room for the requested camera position.
- VS Code with the Python extension is helpful but not required.

## Set up in VS Code

Open this `exercise-tracker` folder in VS Code. Then open **Terminal > New Terminal** and run the commands for your operating system.

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

If PowerShell blocks activation, run the virtual environment's Python directly:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

The MediaPipe pose model downloads automatically into this folder on the first run.

After installing the dependencies, use **Python: Select Interpreter** in VS Code to select the `.venv` interpreter. Then press `F5` and choose **Run Exercise Tracker**, or run `python main.py` in the terminal.

## Controls

- `1` through `9`, then `A` through `F`: select an exercise.
- `M`: show or hide the exercise menu.
- `R`: reset the current exercise.
- `P`: pause or resume tracking.
- `Q`: quit and print all session totals.

The app starts in push-up mode. Counts for other exercises remain available when switching modes until they are reset or the app closes.

## Camera troubleshooting

If the wrong webcam opens:

```bash
python main.py --camera 1
```

Try `--camera 2` if needed. You can request another resolution with:

```bash
python main.py --width 1920 --height 1080
```

Keep the required joints inside the image throughout the full movement. Place the camera far enough away that equipment does not hide elbows, hips, knees, or ankles. A stable camera gives better results than a handheld one.

## Accuracy and tuning

This project uses pose geometry and movement thresholds, not a trained exercise-recognition model. Clothing, camera angle, body proportions, equipment, and partial occlusion can affect counts. The trackers are in `fitness_tracker/exercises.py`; each class keeps its thresholds next to its movement logic so they can be tuned from recorded observations.

Scapular movement is subtle and cannot be measured directly from MediaPipe's external body landmarks. The scapular-squeeze tracker therefore uses bent elbows moving from a narrower to a wider position as a visible proxy. The suitcase-carry timer measures upright posture, not whether a weight is present. The step-up tracker uses knee lift and return, so the camera must include the step to let the user visually confirm each repetition.

This is a fitness aid, not a medical device or a substitute for coaching. Stop if an exercise causes pain.

## Project files

```text
exercise-tracker/
├── .vscode/
│   └── launch.json                 # F5 launch configuration
├── main.py                         # Webcam loop and controls
├── requirements.txt                # Python dependencies
├── README.md                       # Setup and use
└── fitness_tracker/
    ├── __init__.py
    ├── geometry.py                 # Angles, distances, and visibility
    ├── pose.py                     # MediaPipe model and inference
    ├── exercises.py                # All 15 exercise trackers
    └── display.py                  # Skeleton, dashboard, and menu
```

MediaPipe implementation details follow Google's [Pose Landmarker Python guide](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker/python?hl=en).
