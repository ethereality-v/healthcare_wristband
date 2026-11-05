"""MediaPipe model download and pose inference."""

from __future__ import annotations

import os
import shutil
import ssl
import tempfile
import time
import urllib.request
from pathlib import Path

import certifi  # type: ignore[import-not-found]
import mediapipe as mp  # type: ignore[import-not-found]

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
)


def ensure_model(model_path: Path) -> Path:
    """Download the pose model once, using an atomic replacement."""
    model_path = model_path.expanduser().resolve()
    if model_path.exists() and model_path.stat().st_size > 1_000_000:
        return model_path

    model_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading MediaPipe pose model to {model_path} ...")
    context = ssl.create_default_context(cafile=certifi.where())
    temporary_name: str | None = None

    try:
        # Download to a temporary file first so an interrupted download cannot leave
        # a partly written model that looks valid on the next run.
        with tempfile.NamedTemporaryFile(
            mode="wb", delete=False, dir=model_path.parent, suffix=".download"
        ) as temporary_file:
            temporary_name = temporary_file.name
            with urllib.request.urlopen(MODEL_URL, context=context, timeout=60) as response:
                shutil.copyfileobj(response, temporary_file)

        if os.path.getsize(temporary_name) < 1_000_000:
            raise RuntimeError("The downloaded pose model is unexpectedly small.")
        os.replace(temporary_name, model_path)
    except Exception:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)
        raise

    print("Pose model downloaded.")
    return model_path


class PoseEngine:
    """Small context manager around PoseLandmarker in video mode."""

    def __init__(self, model_path: Path, confidence: float = 0.55) -> None:
        options = mp.tasks.vision.PoseLandmarkerOptions(
            # VIDEO mode needs increasing timestamps for every frame.
            base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_poses=1,
            min_pose_detection_confidence=confidence,
            min_pose_presence_confidence=confidence,
            min_tracking_confidence=confidence,
        )
        self._landmarker = mp.tasks.vision.PoseLandmarker.create_from_options(options)
        self._last_timestamp = 0

    def detect(self, rgb_frame):
        # A monotonic clock keeps timestamps moving forward even if the system clock changes.
        timestamp = time.monotonic_ns() // 1_000_000
        timestamp = max(timestamp, self._last_timestamp + 1)
        self._last_timestamp = timestamp
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        result = self._landmarker.detect_for_video(image, timestamp)
        return result.pose_landmarks[0] if result.pose_landmarks else None

    def close(self) -> None:
        # MediaPipe owns native resources that should be released before the window closes.
        self._landmarker.close()

    def __enter__(self) -> "PoseEngine":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
