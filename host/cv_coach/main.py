"""Webcam application for the multi-exercise pose tracker."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2  # type: ignore[import-not-found]

from fitness_tracker.display import draw_dashboard, draw_pose
from fitness_tracker.exercises import EXERCISES, create_trackers
from fitness_tracker.pose import PoseEngine, ensure_model

# Keep the downloaded model beside the application so the project is portable.
PROJECT_DIR = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    # Command-line options make it easy to select another camera without editing code.
    parser = argparse.ArgumentParser(description="Track 15 exercises from a webcam feed.")
    parser.add_argument("--camera", type=int, default=0, help="Webcam index (default: 0)")
    parser.add_argument("--width", type=int, default=1280, help="Requested camera width")
    parser.add_argument("--height", type=int, default=720, help="Requested camera height")
    parser.add_argument("--no-mirror", action="store_true", help="Do not mirror the webcam image")
    parser.add_argument(
        "--model",
        type=Path,
        default=PROJECT_DIR / "pose_landmarker.task",
        help="Pose Landmarker model path",
    )
    return parser.parse_args()


def open_camera(index: int, width: int, height: int):
    """Open the requested webcam and ask it for the preferred resolution."""
    camera = cv2.VideoCapture(index)
    if not camera.isOpened():
        raise RuntimeError(
            f"Could not open webcam {index}. Close other camera apps or try --camera 1."
        )
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    return camera


def main() -> int:
    args = parse_args()
    model_path = ensure_model(args.model)
    camera = open_camera(args.camera, args.width, args.height)

    # Keep one tracker per exercise so switching modes does not erase its progress.
    specs = {spec.hotkey.lower(): spec for spec in EXERCISES}
    trackers = create_trackers()
    selected_key = "4"  # Push-ups are a familiar starting exercise.
    show_menu = True
    paused = False
    fps = 0.0
    previous_frame_time = time.perf_counter()

    print("Multi-Exercise AI Tracker started.")
    print("Press M for the exercise menu, R to reset, P to pause, and Q to quit.")

    try:
        with PoseEngine(model_path) as pose:
            while camera.isOpened():
                success, frame = camera.read()
                if not success:
                    raise RuntimeError("The webcam opened, but no frame could be read.")

                if not args.no_mirror:
                    frame = cv2.flip(frame, 1)

                # Smooth the displayed FPS so it does not jump on every frame.
                now = time.perf_counter()
                elapsed = max(now - previous_frame_time, 1e-6)
                instant_fps = 1.0 / elapsed
                fps = instant_fps if fps == 0.0 else fps * 0.9 + instant_fps * 0.1
                previous_frame_time = now

                tracker = trackers[selected_key]
                spec = specs[selected_key]
                landmarks = None

                if paused:
                    # Timed exercises must be told about the pause so the gap is not counted.
                    tracker.pause(now)
                    view = tracker.view(cue="Tracking is paused. Press P to continue.")
                else:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    landmarks = pose.detect(rgb_frame)
                    if landmarks is None:
                        # A missing pose should not add time to a hold or stretch.
                        tracker.pause(now)
                        view = tracker.missing("No body detected. Move into the camera view.")
                    else:
                        view = tracker.update(landmarks, now)
                        draw_pose(frame, landmarks)

                # Draw the information panels after the skeleton so they stay readable.
                draw_dashboard(frame, spec, view, fps, show_menu, paused)
                cv2.imshow("Multi-Exercise AI Tracker", frame)

                # OpenCV sends keyboard input only while this window has focus.
                key_code = cv2.waitKey(1) & 0xFF
                if key_code == 255:
                    continue
                key = chr(key_code).lower()

                if key == "q":
                    break
                if key == "m":
                    show_menu = not show_menu
                elif key == "r":
                    tracker.reset()
                elif key == "p":
                    paused = not paused
                    tracker.pause(time.perf_counter())
                elif key in specs:
                    selected_key = key
                    show_menu = False
                    trackers[selected_key].pause(time.perf_counter())
    finally:
        # Always release the webcam, even if the loop exits because of an error.
        camera.release()
        cv2.destroyAllWindows()

    print("Tracker closed. Session totals:")
    for spec in EXERCISES:
        tracker = trackers[spec.hotkey.lower()]
        if hasattr(tracker, "active_seconds"):
            print(f"  {spec.name}: {getattr(tracker, 'active_seconds'):.0f} seconds")
        else:
            print(f"  {spec.name}: {tracker.count} reps")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
