"""Geometry helpers for MediaPipe's normalized pose landmarks."""

from __future__ import annotations

import math
from enum import IntEnum
from typing import Iterable, Sequence


class Landmark(IntEnum):
    # These numbers are the landmark IDs used by MediaPipe Pose.
    NOSE = 0
    LEFT_SHOULDER = 11
    RIGHT_SHOULDER = 12
    LEFT_ELBOW = 13
    RIGHT_ELBOW = 14
    LEFT_WRIST = 15
    RIGHT_WRIST = 16
    LEFT_HIP = 23
    RIGHT_HIP = 24
    LEFT_KNEE = 25
    RIGHT_KNEE = 26
    LEFT_ANKLE = 27
    RIGHT_ANKLE = 28
    LEFT_HEEL = 29
    RIGHT_HEEL = 30
    LEFT_FOOT = 31
    RIGHT_FOOT = 32


def point(landmarks: Sequence, index: int) -> tuple[float, float]:
    # MediaPipe gives x and y as values from 0 to 1, not pixel positions.
    item = landmarks[int(index)]
    return float(item.x), float(item.y)


def visibility(landmarks: Sequence, indices: Iterable[int]) -> float:
    # Use the least visible joint because one hidden joint can make a measurement unreliable.
    return min(float(getattr(landmarks[int(i)], "visibility", 1.0)) for i in indices)


def visible(landmarks: Sequence, indices: Iterable[int], threshold: float = 0.5) -> bool:
    return visibility(landmarks, indices) >= threshold


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def midpoint(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0


def angle(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    """Return the smaller 2D angle ABC in degrees."""
    radians = math.atan2(c[1] - b[1], c[0] - b[0]) - math.atan2(
        a[1] - b[1], a[0] - b[0]
    )
    degrees = abs(math.degrees(radians))
    return 360.0 - degrees if degrees > 180.0 else degrees


def joint_angle(landmarks: Sequence, a: int, b: int, c: int) -> float:
    # The middle landmark is the joint whose angle we want to measure.
    return angle(point(landmarks, a), point(landmarks, b), point(landmarks, c))


def shoulder_midpoint(landmarks: Sequence) -> tuple[float, float]:
    return midpoint(
        point(landmarks, Landmark.LEFT_SHOULDER),
        point(landmarks, Landmark.RIGHT_SHOULDER),
    )


def hip_midpoint(landmarks: Sequence) -> tuple[float, float]:
    return midpoint(
        point(landmarks, Landmark.LEFT_HIP),
        point(landmarks, Landmark.RIGHT_HIP),
    )


def ankle_midpoint(landmarks: Sequence) -> tuple[float, float]:
    return midpoint(
        point(landmarks, Landmark.LEFT_ANKLE),
        point(landmarks, Landmark.RIGHT_ANKLE),
    )


def body_line_angle(landmarks: Sequence) -> float:
    return angle(shoulder_midpoint(landmarks), hip_midpoint(landmarks), ankle_midpoint(landmarks))


def torso_length(landmarks: Sequence) -> float:
    # The floor prevents a near-zero torso from making normalized ratios explode.
    return max(distance(shoulder_midpoint(landmarks), hip_midpoint(landmarks)), 0.05)


def shoulder_width(landmarks: Sequence) -> float:
    # Ratios based on shoulder width adapt to different distances from the camera.
    return max(
        distance(
            point(landmarks, Landmark.LEFT_SHOULDER),
            point(landmarks, Landmark.RIGHT_SHOULDER),
        ),
        0.05,
    )


def vertical_lean_degrees(top: tuple[float, float], bottom: tuple[float, float]) -> float:
    """Return deviation in degrees from a vertical line."""
    dx = top[0] - bottom[0]
    dy = top[1] - bottom[1]
    return math.degrees(math.atan2(abs(dx), max(abs(dy), 1e-6)))


def horizontal_slope_degrees(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx = abs(a[0] - b[0])
    dy = abs(a[1] - b[1])
    return math.degrees(math.atan2(dy, max(dx, 1e-6)))
