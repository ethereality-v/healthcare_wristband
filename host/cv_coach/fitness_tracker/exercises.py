"""Exercise-specific, rule-based pose trackers.

Thresholds are intentionally centralized in each tracker so they can be tuned for a
particular camera position or athlete without changing the application loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .geometry import (
    Landmark as L,
    angle,
    ankle_midpoint,
    body_line_angle,
    distance,
    hip_midpoint,
    horizontal_slope_degrees,
    joint_angle,
    midpoint,
    point,
    shoulder_midpoint,
    shoulder_width,
    torso_length,
    vertical_lean_degrees,
    visible,
)

MIN_VISIBILITY = 0.5
LEFT_ARM = (L.LEFT_SHOULDER, L.LEFT_ELBOW, L.LEFT_WRIST)
RIGHT_ARM = (L.RIGHT_SHOULDER, L.RIGHT_ELBOW, L.RIGHT_WRIST)
LEFT_LEG = (L.LEFT_HIP, L.LEFT_KNEE, L.LEFT_ANKLE)
RIGHT_LEG = (L.RIGHT_HIP, L.RIGHT_KNEE, L.RIGHT_ANKLE)
CORE = (L.LEFT_SHOULDER, L.RIGHT_SHOULDER, L.LEFT_HIP, L.RIGHT_HIP)
FULL_BODY = CORE + (L.LEFT_KNEE, L.RIGHT_KNEE, L.LEFT_ANKLE, L.RIGHT_ANKLE)


@dataclass(frozen=True)
class TrackerView:
    value_label: str
    value: str
    stage: str
    metric: str
    cue: str
    detected: bool = True


class ExerciseTracker:
    """Base class for repetition trackers."""

    value_label = "REPS"

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.count = 0
        self.left_count = 0
        self.right_count = 0
        self.stage = "READY"
        self.metric = "Move into position"
        self.cue = "Follow the setup shown in the exercise menu."
        self._last_rep_at = -10.0

    def pause(self, now: float) -> None:
        del now

    def _add_rep(self, now: float, side: str | None = None) -> bool:
        # A short cooldown stops one slow movement from being counted twice.
        if now - self._last_rep_at < 0.3:
            return False
        self.count += 1
        if side == "left":
            self.left_count += 1
        elif side == "right":
            self.right_count += 1
        self._last_rep_at = now
        return True

    def view(self, detected: bool = True, cue: str | None = None) -> TrackerView:
        value = str(self.count)
        if self.left_count or self.right_count:
            value = f"{self.count}  (L {self.left_count} / R {self.right_count})"
        return TrackerView(
            self.value_label,
            value,
            self.stage,
            self.metric,
            cue if cue is not None else self.cue,
            detected,
        )

    def missing(self, cue: str = "Move your full body into the camera view.") -> TrackerView:
        return self.view(False, cue)

    def update(self, landmarks: Sequence, now: float) -> TrackerView:
        raise NotImplementedError


class TimedTracker(ExerciseTracker):
    value_label = "TIME"

    def reset(self) -> None:
        super().reset()
        self.active_seconds = 0.0
        self._last_update: float | None = None

    def pause(self, now: float) -> None:
        # The next valid frame starts a fresh timing interval.
        self._last_update = now

    def _tick(self, valid_position: bool, now: float) -> None:
        # Only time spent in a valid position counts. Invalid frames reset the clock
        # used for the next interval but do not erase the total already earned.
        if self._last_update is not None and valid_position:
            self.active_seconds += min(max(now - self._last_update, 0.0), 0.1)
        self._last_update = now
        self.stage = "HOLD" if valid_position else "ADJUST"

    def view(self, detected: bool = True, cue: str | None = None) -> TrackerView:
        base = super().view(detected, cue)
        minutes, seconds = divmod(int(self.active_seconds), 60)
        value = f"{minutes:02d}:{seconds:02d}" if minutes else f"{seconds}s"
        return TrackerView(base.value_label, value, base.stage, base.metric, base.cue, detected)


class StandingHipOpenerTracker(ExerciseTracker):
    def reset(self) -> None:
        super().reset()
        self._opened = {"left": False, "right": False}

    def update(self, landmarks: Sequence, now: float) -> TrackerView:
        # A side is counted after the knee opens and returns close to the hip.
        if not visible(landmarks, FULL_BODY, MIN_VISIBILITY):
            return self.missing()

        candidates = []
        for side, hip_id, knee_id, ankle_id in (
            ("left", L.LEFT_HIP, L.LEFT_KNEE, L.LEFT_ANKLE),
            ("right", L.RIGHT_HIP, L.RIGHT_KNEE, L.RIGHT_ANKLE),
        ):
            hip, knee = point(landmarks, hip_id), point(landmarks, knee_id)
            knee_angle = joint_angle(landmarks, hip_id, knee_id, ankle_id)
            outward = abs(knee[0] - hip[0]) / shoulder_width(landmarks)
            lift = hip[1] - knee[1]
            candidates.append((lift + outward * 0.15, side, knee_angle, outward, lift))

            is_open = knee_angle < 135 and lift > -0.03 and outward > 0.38
            is_closed = lift < -0.10 or (outward < 0.24 and knee_angle > 145)
            if is_open:
                self._opened[side] = True
            elif is_closed and self._opened[side]:
                self._add_rep(now, side)
                self._opened[side] = False

        _, active_side, knee_angle, outward, lift = max(candidates)
        self.stage = "OPEN" if self._opened[active_side] else "CLOSED"
        self.metric = f"{active_side.title()} knee {knee_angle:.0f} deg | opening {outward:.2f}"
        self.cue = "Lift the knee, rotate it outward, then return the foot under your hip."
        if lift < -0.18:
            self.cue = "Lift one knee to hip height before opening it outward."
        return self.view()


class ScapularSqueezeTracker(ExerciseTracker):
    def update(self, landmarks: Sequence, now: float) -> TrackerView:
        # Shoulder blades are not directly visible, so elbow spread is used as a proxy.
        ids = CORE + (L.LEFT_ELBOW, L.RIGHT_ELBOW, L.LEFT_WRIST, L.RIGHT_WRIST)
        if not visible(landmarks, ids, MIN_VISIBILITY):
            return self.missing("Use a front view and keep both arms visible.")

        elbow_span = distance(point(landmarks, L.LEFT_ELBOW), point(landmarks, L.RIGHT_ELBOW))
        spread = elbow_span / shoulder_width(landmarks)
        elbow_angles = (
            joint_angle(landmarks, *LEFT_ARM),
            joint_angle(landmarks, *RIGHT_ARM),
        )
        bent = sum(elbow_angles) / 2.0 < 135

        if bent and spread > 1.52:
            self.stage = "SQUEEZED"
        elif spread < 1.30 and self.stage == "SQUEEZED":
            if self._add_rep(now):
                self.stage = "RELEASED"
        elif self.stage not in ("SQUEEZED",):
            self.stage = "RELEASED"

        self.metric = f"Elbow spread {spread:.2f}x shoulder width"
        self.cue = "Bend both elbows, open them wide, and squeeze your shoulder blades."
        if not bent:
            self.cue = "Keep both elbows bent near 90 degrees for reliable tracking."
        return self.view()


class LungeTracker(ExerciseTracker):
    def reset(self) -> None:
        super().reset()
        self._down_side: str | None = None

    def update(self, landmarks: Sequence, now: float) -> TrackerView:
        # Store the side that went down so the return to standing completes that rep.
        if not visible(landmarks, FULL_BODY, MIN_VISIBILITY):
            return self.missing("Use a side or 45-degree view with both feet visible.")

        angles = {
            "left": joint_angle(landmarks, *LEFT_LEG),
            "right": joint_angle(landmarks, *RIGHT_LEG),
        }
        active_side = "left" if angles["left"] <= angles["right"] else "right"
        active_angle = angles[active_side]

        if active_angle < 105 and self._down_side is None:
            self._down_side = active_side
            self.stage = "DOWN"
        elif self._down_side and angles[self._down_side] > 155:
            completed_side = self._down_side
            self._add_rep(now, completed_side)
            self._down_side = None
            self.stage = "UP"

        self.metric = f"L knee {angles['left']:.0f} deg | R knee {angles['right']:.0f} deg"
        self.cue = "Lower until the front knee is near 90 degrees, then stand tall."
        return self.view()


class PushUpTracker(ExerciseTracker):
    def update(self, landmarks: Sequence, now: float) -> TrackerView:
        # A push-up is the down phase followed by a straight-arm return.
        ids = FULL_BODY + (L.LEFT_ELBOW, L.RIGHT_ELBOW, L.LEFT_WRIST, L.RIGHT_WRIST)
        if not visible(landmarks, ids, MIN_VISIBILITY):
            return self.missing("Use a side view with shoulders, hips, ankles, and arms visible.")

        elbow_angles = [joint_angle(landmarks, *LEFT_ARM), joint_angle(landmarks, *RIGHT_ARM)]
        elbow_angle = min(elbow_angles)
        line_angle = body_line_angle(landmarks)

        if elbow_angle < 100 and self.stage in ("READY", "UP"):
            self.stage = "DOWN"
        elif elbow_angle > 155 and self.stage == "DOWN":
            if self._add_rep(now):
                self.stage = "UP"

        self.metric = f"Elbow {elbow_angle:.0f} deg | body line {line_angle:.0f} deg"
        self.cue = "Lower your chest, then fully press up."
        if line_angle < 155:
            self.cue = "Keep shoulders, hips, and ankles in one straight line."
        return self.view()


class ChestPressTracker(ExerciseTracker):
    def update(self, landmarks: Sequence, now: float) -> TrackerView:
        # Both arms are averaged so a single noisy elbow does not dominate the state.
        ids = LEFT_ARM + RIGHT_ARM + (L.LEFT_HIP, L.RIGHT_HIP)
        if not visible(landmarks, ids, MIN_VISIBILITY):
            return self.missing("Place the camera where both shoulders, elbows, and wrists are visible.")

        angles = [joint_angle(landmarks, *LEFT_ARM), joint_angle(landmarks, *RIGHT_ARM)]
        elbow_angle = sum(angles) / 2.0
        if elbow_angle < 105 and self.stage in ("READY", "PRESSED"):
            self.stage = "LOWERED"
        elif elbow_angle > 155 and self.stage == "LOWERED":
            if self._add_rep(now):
                self.stage = "PRESSED"

        self.metric = f"Average elbow angle {elbow_angle:.0f} deg"
        self.cue = "Lower both hands under control, then press until the arms are nearly straight."
        return self.view()


class KettlebellSwingTracker(ExerciseTracker):
    def update(self, landmarks: Sequence, now: float) -> TrackerView:
        # The hinge starts with the hands back and finishes when the hips and hands rise.
        ids = CORE + (L.LEFT_WRIST, L.RIGHT_WRIST, L.LEFT_KNEE, L.RIGHT_KNEE)
        if not visible(landmarks, ids, MIN_VISIBILITY):
            return self.missing("Use a side view and keep your hands, shoulders, hips, and knees visible.")

        shoulders = shoulder_midpoint(landmarks)
        hips = hip_midpoint(landmarks)
        wrists = midpoint(point(landmarks, L.LEFT_WRIST), point(landmarks, L.RIGHT_WRIST))
        hip_angles = [
            joint_angle(landmarks, L.LEFT_SHOULDER, L.LEFT_HIP, L.LEFT_KNEE),
            joint_angle(landmarks, L.RIGHT_SHOULDER, L.RIGHT_HIP, L.RIGHT_KNEE),
        ]
        hip_angle = sum(hip_angles) / 2.0
        hands_at_top = wrists[1] < shoulders[1] + torso_length(landmarks) * 0.35
        hands_back = wrists[1] > hips[1] and hip_angle < 135

        if hands_back and self.stage in ("READY", "TOP"):
            self.stage = "HINGE"
        elif hands_at_top and hip_angle > 155 and self.stage == "HINGE":
            if self._add_rep(now):
                self.stage = "TOP"

        self.metric = f"Hip {hip_angle:.0f} deg | hands {'high' if hands_at_top else 'low'}"
        self.cue = "Hinge at the hips, then stand tall and swing to chest height."
        return self.view()


class DeadliftTracker(ExerciseTracker):
    def update(self, landmarks: Sequence, now: float) -> TrackerView:
        # The tracker looks for a hip hinge, then a tall lockout position.
        if not visible(landmarks, FULL_BODY, MIN_VISIBILITY):
            return self.missing("Use a side view with shoulders, hips, knees, and ankles visible.")

        hip_angles = [
            joint_angle(landmarks, L.LEFT_SHOULDER, L.LEFT_HIP, L.LEFT_KNEE),
            joint_angle(landmarks, L.RIGHT_SHOULDER, L.RIGHT_HIP, L.RIGHT_KNEE),
        ]
        hip_angle = sum(hip_angles) / 2.0
        knee_angle = min(joint_angle(landmarks, *LEFT_LEG), joint_angle(landmarks, *RIGHT_LEG))

        if hip_angle < 120 and self.stage in ("READY", "LOCKOUT"):
            self.stage = "HINGE"
        elif hip_angle > 160 and self.stage == "HINGE":
            if self._add_rep(now):
                self.stage = "LOCKOUT"

        self.metric = f"Hip {hip_angle:.0f} deg | knee {knee_angle:.0f} deg"
        self.cue = "Push the hips back, keep the spine neutral, then stand to full lockout."
        if knee_angle < 95:
            self.cue = "Hinge at the hips; avoid turning the deadlift into a deep squat."
        return self.view()


class SeatedRowTracker(ExerciseTracker):
    def update(self, landmarks: Sequence, now: float) -> TrackerView:
        # Pulling bends the elbows; extending them returns the tracker to its ready state.
        ids = LEFT_ARM + RIGHT_ARM + (L.LEFT_HIP, L.RIGHT_HIP)
        if not visible(landmarks, ids, MIN_VISIBILITY):
            return self.missing("Use a side or 45-degree view with both arms visible.")

        angles = [joint_angle(landmarks, *LEFT_ARM), joint_angle(landmarks, *RIGHT_ARM)]
        elbow_angle = sum(angles) / 2.0
        lean = vertical_lean_degrees(shoulder_midpoint(landmarks), hip_midpoint(landmarks))

        if elbow_angle < 95 and self.stage in ("READY", "EXTENDED"):
            self.stage = "PULLED"
        elif elbow_angle > 150 and self.stage == "PULLED":
            if self._add_rep(now):
                self.stage = "EXTENDED"

        self.metric = f"Elbow {elbow_angle:.0f} deg | torso lean {lean:.0f} deg"
        self.cue = "Pull elbows behind you, pause, then extend the arms under control."
        if lean > 25:
            self.cue = "Keep your torso still instead of rocking through the repetition."
        return self.view()


class LatPulldownTracker(ExerciseTracker):
    def update(self, landmarks: Sequence, now: float) -> TrackerView:
        # A rep runs from arms overhead to elbows down and back overhead.
        ids = LEFT_ARM + RIGHT_ARM + (L.LEFT_HIP, L.RIGHT_HIP)
        if not visible(landmarks, ids, MIN_VISIBILITY):
            return self.missing("Use a front view with both arms and your torso visible.")

        elbows = [joint_angle(landmarks, *LEFT_ARM), joint_angle(landmarks, *RIGHT_ARM)]
        shoulder_angles = [
            joint_angle(landmarks, L.LEFT_HIP, L.LEFT_SHOULDER, L.LEFT_ELBOW),
            joint_angle(landmarks, L.RIGHT_HIP, L.RIGHT_SHOULDER, L.RIGHT_ELBOW),
        ]
        elbow_angle = sum(elbows) / 2.0
        shoulder_angle = sum(shoulder_angles) / 2.0
        overhead = shoulder_angle > 140 and elbow_angle > 140
        pulled = shoulder_angle < 100 and elbow_angle < 115

        if pulled and self.stage in ("READY", "OVERHEAD"):
            self.stage = "PULLED"
        elif overhead and self.stage == "PULLED":
            if self._add_rep(now):
                self.stage = "OVERHEAD"
        elif overhead and self.stage == "READY":
            self.stage = "OVERHEAD"

        self.metric = f"Shoulder {shoulder_angle:.0f} deg | elbow {elbow_angle:.0f} deg"
        self.cue = "Pull both elbows down, then return the arms fully overhead."
        return self.view()


class SuitcaseCarryTracker(TimedTracker):
    def update(self, landmarks: Sequence, now: float) -> TrackerView:
        # Carry time is earned only while the torso is upright and shoulders are level.
        if not visible(landmarks, FULL_BODY, MIN_VISIBILITY):
            self.pause(now)
            return self.missing("Use a front view and keep your full body visible while walking.")

        lean = vertical_lean_degrees(shoulder_midpoint(landmarks), hip_midpoint(landmarks))
        shoulders = point(landmarks, L.LEFT_SHOULDER), point(landmarks, L.RIGHT_SHOULDER)
        level = abs(shoulders[0][1] - shoulders[1][1]) / torso_length(landmarks)
        valid = lean < 12 and level < 0.16
        self._tick(valid, now)
        self.metric = f"Torso lean {lean:.0f} deg | shoulder tilt {level:.2f}"
        self.cue = "Walk tall without leaning toward or away from the carried weight."
        if not valid:
            self.cue = "Stack your shoulders over your hips and level your shoulders."
        return self.view()


class PlankTracker(TimedTracker):
    def update(self, landmarks: Sequence, now: float) -> TrackerView:
        # A side-view body line is used to decide whether the plank position is valid.
        if not visible(landmarks, FULL_BODY, MIN_VISIBILITY):
            self.pause(now)
            return self.missing("Use a side view with shoulders, hips, and ankles visible.")

        line = body_line_angle(landmarks)
        slope = horizontal_slope_degrees(shoulder_midpoint(landmarks), ankle_midpoint(landmarks))
        valid = line > 160 and slope < 35
        self._tick(valid, now)
        self.metric = f"Body line {line:.0f} deg | floor angle {slope:.0f} deg"
        self.cue = "Keep your body straight and parallel to the floor."
        if line <= 160:
            self.cue = "Raise or lower your hips to make a straight body line."
        elif slope >= 35:
            self.cue = "Use a side view and move into a horizontal plank position."
        return self.view()


class MountainClimberTracker(ExerciseTracker):
    def reset(self) -> None:
        super().reset()
        self._ready = {"left": True, "right": True}

    def update(self, landmarks: Sequence, now: float) -> TrackerView:
        # Each knee must move away from the chest before it can count again.
        if not visible(landmarks, FULL_BODY, MIN_VISIBILITY):
            return self.missing("Use a side or 45-degree view with both knees visible.")

        torso = torso_length(landmarks)
        ratios = {}
        for side, shoulder_id, hip_id, knee_id in (
            ("left", L.LEFT_SHOULDER, L.LEFT_HIP, L.LEFT_KNEE),
            ("right", L.RIGHT_SHOULDER, L.RIGHT_HIP, L.RIGHT_KNEE),
        ):
            target = midpoint(point(landmarks, shoulder_id), point(landmarks, hip_id))
            ratio = distance(point(landmarks, knee_id), target) / torso
            ratios[side] = ratio
            if ratio < 0.72 and self._ready[side]:
                self._add_rep(now, side)
                self._ready[side] = False
                self.stage = f"{side.upper()} DRIVE"
            elif ratio > 1.02:
                self._ready[side] = True

        self.metric = f"L knee {ratios['left']:.2f} | R knee {ratios['right']:.2f}"
        self.cue = "Drive one knee toward your chest, extend it back, then alternate."
        if body_line_angle(landmarks) < 145:
            self.cue = "Keep your hips from sagging while you alternate knees."
        return self.view()


class HamstringStretchTracker(TimedTracker):
    def update(self, landmarks: Sequence, now: float) -> TrackerView:
        # The timer starts when a straight leg and a forward hip hinge are both present.
        if not visible(landmarks, FULL_BODY, MIN_VISIBILITY):
            self.pause(now)
            return self.missing("Use a side view with your full body visible.")

        left_knee = joint_angle(landmarks, *LEFT_LEG)
        right_knee = joint_angle(landmarks, *RIGHT_LEG)
        hip_angles = [
            joint_angle(landmarks, L.LEFT_SHOULDER, L.LEFT_HIP, L.LEFT_KNEE),
            joint_angle(landmarks, L.RIGHT_SHOULDER, L.RIGHT_HIP, L.RIGHT_KNEE),
        ]
        straight_knee = max(left_knee, right_knee)
        hip_angle = min(hip_angles)
        valid = straight_knee > 155 and hip_angle < 125
        self._tick(valid, now)
        self.metric = f"Straight knee {straight_knee:.0f} deg | hip fold {hip_angle:.0f} deg"
        self.cue = "Keep the stretching leg straight and hinge forward from the hips."
        if straight_knee <= 155:
            self.cue = "Straighten the stretching knee without locking it painfully."
        elif hip_angle >= 125:
            self.cue = "Hinge forward from your hips until you feel a gentle stretch."
        return self.view()


class CalfStretchTracker(TimedTracker):
    def update(self, landmarks: Sequence, now: float) -> TrackerView:
        # The split stance and straight back leg are the visible signs of a calf stretch.
        if not visible(landmarks, FULL_BODY, MIN_VISIBILITY):
            self.pause(now)
            return self.missing("Use a side view with both feet fully visible.")

        left_knee = joint_angle(landmarks, *LEFT_LEG)
        right_knee = joint_angle(landmarks, *RIGHT_LEG)
        ankle_separation = distance(
            point(landmarks, L.LEFT_ANKLE), point(landmarks, L.RIGHT_ANKLE)
        ) / torso_length(landmarks)
        back_leg_angle = max(left_knee, right_knee)
        lean = vertical_lean_degrees(shoulder_midpoint(landmarks), hip_midpoint(landmarks))
        valid = ankle_separation > 0.75 and back_leg_angle > 155 and lean < 35
        self._tick(valid, now)
        self.metric = f"Stance {ankle_separation:.2f}x torso | straight knee {back_leg_angle:.0f} deg"
        self.cue = "Use a split stance, keep the back knee straight, and press its heel down."
        if ankle_separation <= 0.75:
            self.cue = "Move one foot farther back into a split stance."
        elif back_leg_angle <= 155:
            self.cue = "Straighten the back knee and keep the back heel down."
        return self.view()


class StepUpTracker(ExerciseTracker):
    def reset(self) -> None:
        super().reset()
        self._raised = {"left": False, "right": False}

    def update(self, landmarks: Sequence, now: float) -> TrackerView:
        # A raised knee starts the step; returning it down completes the count.
        if not visible(landmarks, FULL_BODY, MIN_VISIBILITY):
            return self.missing("Use a side or 45-degree view and keep the step and full body visible.")

        metrics = {}
        for side, hip_id, knee_id, ankle_id in (
            ("left", L.LEFT_HIP, L.LEFT_KNEE, L.LEFT_ANKLE),
            ("right", L.RIGHT_HIP, L.RIGHT_KNEE, L.RIGHT_ANKLE),
        ):
            hip, knee = point(landmarks, hip_id), point(landmarks, knee_id)
            lift = (hip[1] - knee[1]) / torso_length(landmarks)
            knee_angle = joint_angle(landmarks, hip_id, knee_id, ankle_id)
            metrics[side] = (lift, knee_angle)

            if lift > -0.05 and knee_angle < 125 and not self._raised[side]:
                self._raised[side] = True
                self.stage = f"{side.upper()} STEP"
            elif lift < -0.35 and self._raised[side]:
                self._add_rep(now, side)
                self._raised[side] = False
                self.stage = "DOWN"

        self.metric = f"L lift {metrics['left'][0]:.2f} | R lift {metrics['right'][0]:.2f}"
        self.cue = "Step up, bring the trailing knee through, then return to the floor."
        return self.view()


@dataclass(frozen=True)
class ExerciseSpec:
    # Keeping the key, name, camera view, and tracker together keeps the menu simple.
    hotkey: str
    name: str
    camera: str
    tracker_type: type[ExerciseTracker]


EXERCISES = [
    ExerciseSpec("1", "Standing Hip Opener / Closer", "Front view, full body", StandingHipOpenerTracker),
    ExerciseSpec("2", "Scapular Squeezes", "Front view, arms bent", ScapularSqueezeTracker),
    ExerciseSpec("3", "Lunges", "Side or 45-degree view", LungeTracker),
    ExerciseSpec("4", "Push-ups", "Side view, full body", PushUpTracker),
    ExerciseSpec("5", "Chest Press", "45-degree view, both arms", ChestPressTracker),
    ExerciseSpec("6", "Kettlebell Swings", "Side view, full body", KettlebellSwingTracker),
    ExerciseSpec("7", "Deadlifts", "Side view, full body", DeadliftTracker),
    ExerciseSpec("8", "Seated Row", "Side or 45-degree view", SeatedRowTracker),
    ExerciseSpec("9", "Lat Pulldown", "Front view, upper body", LatPulldownTracker),
    ExerciseSpec("A", "Suitcase Carry", "Front view, full body", SuitcaseCarryTracker),
    ExerciseSpec("B", "Plank", "Side view, full body", PlankTracker),
    ExerciseSpec("C", "Mountain Climbers", "Side or 45-degree view", MountainClimberTracker),
    ExerciseSpec("D", "Hamstring Stretch", "Side view, full body", HamstringStretchTracker),
    ExerciseSpec("E", "Calf Stretch", "Side view, both feet", CalfStretchTracker),
    ExerciseSpec("F", "Step-ups", "Side or 45-degree view", StepUpTracker),
]


def create_trackers() -> dict[str, ExerciseTracker]:
    # Each mode gets its own state object so switching exercises preserves its count.
    return {spec.hotkey.lower(): spec.tracker_type() for spec in EXERCISES}
