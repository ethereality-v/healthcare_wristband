"""Small OpenCV drawing helpers for the tracker window."""

from __future__ import annotations

import cv2  # type: ignore[import-not-found]

from .exercises import EXERCISES, ExerciseSpec, TrackerView

# These colors are deliberately limited so the screen stays easy to read.
BACKGROUND = (24, 28, 36)
WHITE = (242, 244, 247)
MUTED = (185, 192, 202)
GREEN = (77, 218, 138)
BLUE = (80, 210, 255)
RED = (60, 80, 255)
POSE_LINE = (77, 218, 138)
POSE_POINT = (39, 82, 245)
VISIBILITY_THRESHOLD = 0.5

# MediaPipe landmark pairs used for the skeleton overlay.
CONNECTIONS = (
    (0, 11), (0, 12),
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
    (11, 23), (12, 24), (23, 24),
    (23, 25), (25, 27), (27, 29), (29, 31),
    (24, 26), (26, 28), (28, 30), (30, 32),
)


def _text(
    frame,
    text: str,
    position: tuple[int, int],
    scale: float = 0.65,
    color: tuple[int, int, int] = WHITE,
    thickness: int = 2,
) -> None:
    """Draw readable text with a small dark outline."""
    x, y = position
    cv2.putText(
        frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
        scale, (0, 0, 0), thickness + 3, cv2.LINE_AA,
    )
    cv2.putText(
        frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
        scale, color, thickness, cv2.LINE_AA,
    )


def _panel(frame, x1: int, y1: int, x2: int, y2: int, opacity: float = 0.82) -> None:
    """Place a slightly transparent dark panel over the camera image."""
    overlay = frame.copy()
    cv2.rectangle(overlay, (x1, y1), (x2, y2), BACKGROUND, -1)
    cv2.addWeighted(overlay, opacity, frame, 1.0 - opacity, 0, frame)


def _wrap_text(frame, text: str, max_width: int, scale: float, thickness: int) -> list[str]:
    """Wrap a cue based on its pixel width instead of its character count."""
    words = text.split()
    lines: list[str] = []
    current = ""

    for word in words:
        candidate = word if not current else f"{current} {word}"
        text_width = cv2.getTextSize(
            candidate, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness
        )[0][0]
        if current and text_width > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate

    if current:
        lines.append(current)
    return lines[:2]


def draw_pose(frame, landmarks) -> None:
    """Draw visible body connections and points over the live frame."""
    height, width = frame.shape[:2]

    for start, end in CONNECTIONS:
        first, second = landmarks[start], landmarks[end]
        if min(
            getattr(first, "visibility", 1.0),
            getattr(second, "visibility", 1.0),
        ) < VISIBILITY_THRESHOLD:
            continue

        first_point = (int(first.x * width), int(first.y * height))
        second_point = (int(second.x * width), int(second.y * height))
        cv2.line(frame, first_point, second_point, POSE_LINE, 3, cv2.LINE_AA)

    for landmark in landmarks:
        if getattr(landmark, "visibility", 1.0) < VISIBILITY_THRESHOLD:
            continue
        center = (int(landmark.x * width), int(landmark.y * height))
        cv2.circle(frame, center, 5, POSE_POINT, -1, cv2.LINE_AA)
        cv2.circle(frame, center, 7, WHITE, 1, cv2.LINE_AA)


def draw_dashboard(
    frame,
    spec: ExerciseSpec,
    view: TrackerView,
    fps: float,
    show_menu: bool,
    paused: bool,
) -> None:
    """Draw the current exercise, status, instructions, and keyboard hints."""
    height, width = frame.shape[:2]
    panel_width = min(540, width - 20)
    panel_height = 245
    _panel(frame, 10, 10, panel_width, panel_height)

    # The exercise name and camera advice form the main heading.
    _text(frame, spec.name, (28, 42), 0.78, GREEN, 2)
    _text(frame, f"Camera: {spec.camera}", (28, 66), 0.48, MUTED, 1)

    # The large value is the most important piece of feedback on the screen.
    _text(frame, f"{view.value_label}: {view.value}", (28, 108), 0.88, WHITE, 2)
    status_color = BLUE if view.detected else RED
    _text(frame, f"STATUS: {view.stage}", (28, 140), 0.60, status_color, 2)
    _text(frame, view.metric, (28, 168), 0.52, WHITE, 1)

    # Form advice is allowed two lines so long messages remain readable.
    cue_lines = _wrap_text(frame, view.cue, panel_width - 42, 0.52, 1)
    for line_number, line in enumerate(cue_lines):
        _text(frame, line, (28, 195 + line_number * 20), 0.52, BLUE, 1)

    _text(frame, f"FPS {fps:.0f}", (width - 88, 28), 0.45, MUTED, 1)
    _text(frame, "[M] Menu   [R] Reset   [P] Pause   [Q] Quit", (18, height - 18), 0.48, WHITE, 1)

    if paused:
        # This small overlay makes it obvious that counts and timers are stopped.
        overlay_width = 250
        x1 = max(0, width // 2 - overlay_width // 2)
        x2 = min(width, width // 2 + overlay_width // 2)
        _panel(frame, x1, height // 2 - 45, x2, height // 2 + 45, 0.92)
        _text(frame, "PAUSED", (width // 2 - 72, height // 2 + 10), 0.95, BLUE, 3)

    if show_menu:
        draw_menu(frame, spec)


def draw_menu(frame, selected: ExerciseSpec) -> None:
    """Draw a plain exercise list on the right side of the camera view."""
    height, width = frame.shape[:2]
    menu_width = min(420, max(280, width - 20))
    x1 = max(10, width - menu_width - 10)
    x2 = width - 10
    y1 = 42
    footer_height = 38
    menu_height = min(height - 55, 570)
    y2 = y1 + menu_height
    _panel(frame, x1, y1, x2, y2, 0.94)

    _text(frame, "EXERCISES", (x1 + 18, y1 + 31), 0.68, GREEN, 2)
    cv2.line(frame, (x1 + 16, y1 + 45), (x2 - 16, y1 + 45), (75, 82, 94), 1)

    # Fit all options between the heading and the footer, even at smaller sizes.
    available_height = max(1, menu_height - 65 - footer_height)
    row_height = max(24, available_height // len(EXERCISES))
    font_scale = 0.48 if row_height >= 27 else 0.42
    y = y1 + 70

    for exercise in EXERCISES:
        active = exercise.hotkey == selected.hotkey
        if active:
            cv2.rectangle(
                frame,
                (x1 + 9, y - 20),
                (x2 - 9, y + 7),
                (55, 70, 78),
                -1,
            )

        color = BLUE if active else WHITE
        prefix = ">" if active else " "
        _text(
            frame,
            f"{prefix} [{exercise.hotkey}] {exercise.name}",
            (x1 + 16, y),
            font_scale,
            color,
            1,
        )
        y += row_height

    _text(frame, "Press a key to switch exercises", (x1 + 18, y2 - 15), 0.45, MUTED, 1)
