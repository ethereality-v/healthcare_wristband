"""Professional, low-distraction UI for the live exercise coach."""

from __future__ import annotations

import cv2  # type: ignore[import-not-found]

from .exercises import EXERCISES, ExerciseSpec, TrackerView

# OpenCV uses BGR color order.
INK = (22, 27, 34)
SURFACE = (31, 38, 47)
SURFACE_RAISED = (42, 51, 61)
RULE = (72, 84, 96)
TEXT = (238, 241, 244)
MUTED = (164, 175, 186)
ACCENT = (116, 190, 132)
INFO = (196, 175, 93)
ALERT = (95, 100, 220)
POSE_LINE = (116, 190, 132)
POSE_POINT = (214, 128, 78)

VISIBILITY_THRESHOLD = 0.5

CONNECTIONS = (
    (0, 11),
    (0, 12),
    (11, 12),
    (11, 13),
    (13, 15),
    (12, 14),
    (14, 16),
    (11, 23),
    (12, 24),
    (23, 24),
    (23, 25),
    (25, 27),
    (27, 29),
    (29, 31),
    (24, 26),
    (26, 28),
    (28, 30),
    (30, 32),
)

def _text(
    frame,
    text: str,
    position: tuple[int, int],
    scale: float = 0.65,
    color: tuple[int, int, int] = TEXT,
    thickness: int = 1,
) -> None:
    """Draw a clean single-pass text label."""
    x, y = position

    # A single text pass prevents ghosting and visual artifacts.
    cv2.putText(
        frame,
        text,
        (x, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        color,
        thickness,
        cv2.LINE_AA,
    )

def _panel(
    frame,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    opacity: float = 0.90,
    border: bool = True,
) -> None:
    """Draw a flat translucent panel."""
    overlay = frame.copy()

    cv2.rectangle(
        overlay,
        (x1, y1),
        (x2, y2),
        SURFACE,
        -1,
    )

    cv2.addWeighted(
        overlay,
        opacity,
        frame,
        1.0 - opacity,
        0,
        frame,
    )

    if border:
        cv2.rectangle(
            frame,
            (x1, y1),
            (x2, y2),
            RULE,
            1,
            cv2.LINE_AA,
        )

def _rule(
    frame,
    x1: int,
    y: int,
    x2: int,
    color: tuple[int, int, int] = RULE,
) -> None:
    """Draw a divider line."""
    cv2.line(
        frame,
        (x1, y),
        (x2, y),
        color,
        1,
        cv2.LINE_AA,
    )

def _fit_text(
    text: str,
    max_width: int,
    scale: float,
    thickness: int = 1,
) -> str:
    """Shorten text when it does not fit in the available width."""
    text_width = cv2.getTextSize(
        text,
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        thickness,
    )[0][0]

    if text_width <= max_width:
        return text

    shortened = text

    while shortened:
        candidate = shortened.rstrip() + "..."

        candidate_width = cv2.getTextSize(
            candidate,
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            thickness,
        )[0][0]

        if candidate_width <= max_width:
            return candidate

        shortened = shortened[:-1]

    return "..."

def _wrap_text(
    text: str,
    max_width: int,
    scale: float,
    thickness: int = 1,
) -> list[str]:
    """Wrap coaching text according to its rendered width."""
    lines: list[str] = []
    current = ""

    for word in text.split():
        candidate = word if not current else f"{current} {word}"

        candidate_width = cv2.getTextSize(
            candidate,
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            thickness,
        )[0][0]

        if current and candidate_width > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate

    if current:
        lines.append(current)

    return lines[:2]

def _status_dot(
    frame,
    center: tuple[int, int],
    active: bool,
) -> None:
    """Draw the tracking status indicator."""
    color = ACCENT if active else ALERT

    cv2.circle(
        frame,
        center,
        5,
        color,
        -1,
        cv2.LINE_AA,
    )

    cv2.circle(
        frame,
        center,
        8,
        color,
        1,
        cv2.LINE_AA,
    )

def draw_pose(frame, landmarks) -> None:
    """Draw the visible body outline."""
    height, width = frame.shape[:2]

    for start, end in CONNECTIONS:
        first = landmarks[start]
        second = landmarks[end]

        first_visibility = getattr(first, "visibility", 1.0)
        second_visibility = getattr(second, "visibility", 1.0)

        if min(first_visibility, second_visibility) < VISIBILITY_THRESHOLD:
            continue

        first_point = (
            int(first.x * width),
            int(first.y * height),
        )

        second_point = (
            int(second.x * width),
            int(second.y * height),
        )

        cv2.line(
            frame,
            first_point,
            second_point,
            POSE_LINE,
            2,
            cv2.LINE_AA,
        )

    for landmark in landmarks:
        if getattr(landmark, "visibility", 1.0) < VISIBILITY_THRESHOLD:
            continue

        center = (
            int(landmark.x * width),
            int(landmark.y * height),
        )

        cv2.circle(
            frame,
            center,
            4,
            POSE_POINT,
            -1,
            cv2.LINE_AA,
        )

        cv2.circle(
            frame,
            center,
            6,
            TEXT,
            1,
            cv2.LINE_AA,
        )

def _draw_top_bar(
    frame,
    fps: float,
) -> None:
    """Draw the application name and performance readout."""
    height, width = frame.shape[:2]
    bar_height = 58

    _panel(
        frame,
        0,
        0,
        width,
        bar_height,
        0.94,
        border=False,
    )

    _rule(
        frame,
        0,
        bar_height,
        width,
        (86, 99, 111),
    )

    _text(
        frame,
        "MOVE",
        (24, 35),
        0.66,
        ACCENT,
        2,
    )

    _text(
        frame,
        "/  REHABILITATION COACH",
        (91, 34),
        0.48,
        MUTED,
        1,
    )

    _text(
        frame,
        f"{fps:.0f} FPS",
        (width - 66, 34),
        0.40,
        MUTED,
        1,
    )

def _draw_current_exercise(
    frame,
    spec: ExerciseSpec,
    view: TrackerView,
) -> None:
    """Draw the main exercise information panel."""
    height, width = frame.shape[:2]

    x1 = 22
    y1 = 78

    x2 = min(
        452,
        max(380, width - 28),
    )

    y2 = min(
        height - 66,
        390,
    )

    left = x1 + 22
    right = x2 - 22
    content_width = right - left

    _panel(
        frame,
        x1,
        y1,
        x2,
        y2,
        0.92,
    )

    status = "TRACKING" if view.detected else "NO PERSON DETECTED"
    status_color = ACCENT if view.detected else ALERT
    status_scale = 0.34 if not view.detected else 0.40
    status_x = max(left + 150, right - 148)

    _text(
        frame,
        "CURRENT EXERCISE",
        (left, y1 + 28),
        0.40,
        MUTED,
        1,
    )

    _status_dot(
        frame,
        (status_x - 11, y1 + 22),
        view.detected,
    )

    _text(
        frame,
        status,
        (status_x, y1 + 27),
        status_scale,
        status_color,
        1,
    )

    _text(
        frame,
        spec.name,
        (left, y1 + 66),
        0.72,
        TEXT,
        2,
    )

    _text(
        frame,
        f"Camera position  /  {spec.camera}",
        (left, y1 + 91),
        0.41,
        MUTED,
        1,
    )

    _rule(
        frame,
        left,
        y1 + 111,
        right,
    )

    _text(
        frame,
        view.value_label,
        (left, y1 + 143),
        0.40,
        MUTED,
        1,
    )

    value_scale = 1.18 if len(view.value) < 12 else 0.86

    _text(
        frame,
        view.value,
        (left, y1 + 193),
        value_scale,
        TEXT,
        2,
    )

    phase = _fit_text(
        f"PHASE  {view.stage}",
        content_width,
        0.45,
    )

    metric = _fit_text(
        view.metric,
        content_width,
        0.43,
    )

    _text(
        frame,
        phase,
        (left, y1 + 225),
        0.45,
        INFO if view.detected else ALERT,
        1,
    )

    _text(
        frame,
        metric,
        (left, y1 + 250),
        0.43,
        MUTED,
        1,
    )

    cue_lines = _wrap_text(
        view.cue,
        content_width,
        0.43,
    )

    for index, line in enumerate(cue_lines):
        _text(
            frame,
            line,
            (left, y1 + 282 + index * 19),
            0.43,
            INFO,
            1,
        )

def _draw_controls(frame) -> None:
    """Draw the keyboard controls at the bottom."""
    height, width = frame.shape[:2]
    bar_y = max(0, height - 42)

    _panel(
        frame,
        0,
        bar_y,
        width,
        height,
        0.94,
        border=False,
    )

    controls = (
        ("M", "MENU", 22),
        ("R", "RESET", 112),
        ("P", "PAUSE", 215),
        ("Q", "QUIT", 320),
    )

    for key, label, x in controls:
        _text(
            frame,
            key,
            (x, height - 16),
            0.44,
            ACCENT,
            1,
        )

        _text(
            frame,
            label,
            (x + 20, height - 16),
            0.40,
            MUTED,
            1,
        )

    _text(
        frame,
        "1-9, A-F  EXERCISES",
        (width - 190, height - 16),
        0.40,
        MUTED,
        1,
    )

def draw_menu(
    frame,
    selected: ExerciseSpec,
) -> None:
    """Draw the exercise selection library."""
    height, width = frame.shape[:2]

    menu_width = min(
        390,
        max(310, width - 480),
    )

    x1 = max(
        470,
        width - menu_width - 22,
    )

    x2 = min(
        width - 22,
        x1 + menu_width,
    )

    y1 = 78

    y2 = max(
        y1 + 300,
        height - 66,
    )

    menu_height = y2 - y1

    _panel(
        frame,
        x1,
        y1,
        x2,
        y2,
        0.94,
    )

    left = x1 + 20
    right = x2 - 20

    _text(
        frame,
        "EXERCISES",
        (left, y1 + 31),
        0.62,
        TEXT,
        2,
    )

    _text(
        frame,
        "Select a movement to begin",
        (left, y1 + 53),
        0.41,
        MUTED,
        1,
    )

    _rule(
        frame,
        left,
        y1 + 70,
        right,
    )

    footer_height = 34

    available_height = max(
        1,
        menu_height - 92 - footer_height,
    )

    row_height = max(
        24,
        available_height // len(EXERCISES),
    )

    font_scale = 0.47 if row_height >= 28 else 0.40
    y = y1 + 96

    for exercise in EXERCISES:
        active = exercise.hotkey == selected.hotkey

        if active:
            cv2.rectangle(
                frame,
                (x1 + 9, y - 18),
                (x1 + 13, y + 8),
                ACCENT,
                -1,
            )

            cv2.rectangle(
                frame,
                (x1 + 14, y - 18),
                (x2 - 12, y + 8),
                SURFACE_RAISED,
                -1,
            )

        _text(
            frame,
            exercise.hotkey,
            (left, y),
            font_scale,
            ACCENT if active else MUTED,
            1,
        )

        _text(
            frame,
            exercise.name,
            (left + 30, y),
            font_scale,
            TEXT if active else (215, 220, 225),
            1,
        )

        y += row_height

    _rule(
        frame,
        left,
        y2 - footer_height,
        right,
    )

    _text(
        frame,
        "Press a key to switch",
        (left, y2 - 13),
        0.40,
        MUTED,
        1,
    )

def _draw_pause_overlay(frame) -> None:
    """Dim the frame and show how to resume."""
    height, width = frame.shape[:2]

    overlay = frame.copy()

    cv2.rectangle(
        overlay,
        (0, 0),
        (width, height),
        INK,
        -1,
    )

    cv2.addWeighted(
        overlay,
        0.30,
        frame,
        0.70,
        0,
        frame,
    )

    box_width = min(
        310,
        width - 32,
    )

    box_height = 112

    x1 = max(
        16,
        width // 2 - box_width // 2,
    )

    y1 = max(
        65,
        height // 2 - box_height // 2,
    )

    x2 = min(
        width - 16,
        x1 + box_width,
    )

    y2 = min(
        height - 52,
        y1 + box_height,
    )

    _panel(
        frame,
        x1,
        y1,
        x2,
        y2,
        0.97,
    )

    _text(
        frame,
        "SESSION PAUSED",
        (x1 + 27, y1 + 44),
        0.68,
        TEXT,
        2,
    )

    _text(
        frame,
        "Press P to resume",
        (x1 + 27, y1 + 77),
        0.46,
        MUTED,
        1,
    )

def draw_dashboard(
    frame,
    spec: ExerciseSpec,
    view: TrackerView,
    fps: float,
    show_menu: bool,
    paused: bool,
) -> None:
    """Draw the complete camera interface."""
    _draw_top_bar(
        frame,
        fps,
    )

    _draw_current_exercise(
        frame,
        spec,
        view,
    )

    if show_menu:
        draw_menu(
            frame,
            spec,
        )

    if paused:
        _draw_pause_overlay(frame)

    _draw_controls(frame)
