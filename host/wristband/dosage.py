"""Dosage suggestions after a session: progress, keep, or regress each exercise.

Suggestions are flagged for the kinesiologist. Nothing changes the prescription until a
clinician accepts it on the dashboard (POST /api/patients/<id>/prescription).
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .prescription import TYPICAL_REPS, TYPICAL_SETS, Prescription

PROGRESS, KEEP, REGRESS = "progress", "keep", "regress"


def _completion(exercise_record: dict) -> Optional[float]:
    sets = exercise_record.get("sets", [])
    target = sum(s.get("target", 0) for s in sets)
    if not sets or target <= 0:
        return None
    done = sum(min(s.get("count", 0), s.get("target", 0)) for s in sets)
    return done / target


def suggest(session: dict, prescription: Prescription, limits: Optional[dict] = None) -> List[dict]:
    """Returns one suggestion per prescribed exercise that was attempted in the session."""
    limits = limits or {}
    rpe = session.get("rpe")  # Borg 6-20, entered by patient/instructor after the session
    stops = [a for a in session.get("alerts", []) if a.get("level") == "stop"]
    by_id: Dict[str, dict] = {e["exercise"]: e for e in session.get("exercises", [])}
    zone_high = limits.get("zone_high")

    out: List[dict] = []
    for item in prescription.exercises:
        rec = by_id.get(item.exercise)
        if rec is None or rec.get("tracker") == "timer":
            continue
        completion = _completion(rec)
        reasons: List[str] = []
        new_target, new_sets = item.target, item.sets

        # heart rate during this exercise's sets
        hr_values = [v["hr"] for v in rec.get("vitals", []) if v.get("hr_valid")]
        hr_peak = max(hr_values) if hr_values else None
        exercise_stops = [a for a in stops if a.get("exercise") == item.exercise]

        partial = sum(s.get("partial", 0) for s in rec.get("sets", []))

        if exercise_stops:
            action = REGRESS
            reasons.append("a safety stop happened during this exercise")
        elif completion is None:
            action = KEEP
            reasons.append("not enough data")
        elif completion < 0.7:
            action = REGRESS
            reasons.append(f"completed {completion:.0%} of the prescribed volume")
        elif completion >= 1.0 and (rpe is None or rpe <= 13) and (
            hr_peak is None or zone_high is None or hr_peak <= zone_high
        ) and partial <= 1:
            action = PROGRESS
            reasons.append("all sets completed")
            if rpe is not None:
                reasons.append(f"RPE {rpe} (light to somewhat hard)")
            if hr_peak is not None and zone_high is not None:
                reasons.append(f"peak HR {hr_peak} stayed within the zone")
        else:
            action = KEEP
            if completion < 1.0:
                reasons.append(f"completed {completion:.0%} of the prescribed volume")
            if rpe is not None and rpe > 13:
                reasons.append(f"RPE {rpe} was hard")
            if hr_peak is not None and zone_high is not None and hr_peak > zone_high:
                reasons.append(f"peak HR {hr_peak} went above the zone ({zone_high})")
            if partial > 1:
                reasons.append(f"{partial} reps didn't reach the full range of motion")

        unit = rec.get("unit", "reps")
        if action == PROGRESS:
            if unit == "reps" and item.target < TYPICAL_REPS[1]:
                new_target = min(item.target + 2, TYPICAL_REPS[1])
            elif item.sets < TYPICAL_SETS[1]:
                new_sets, new_target = item.sets + 1, (TYPICAL_REPS[0] if unit == "reps" else item.target)
            elif unit != "reps":
                new_target = int(round(item.target * 1.15))
            else:
                reasons.append("at 20 reps x 2 sets: consider a harder variation or more load")
        elif action == REGRESS:
            if item.sets > 1:
                new_sets = item.sets - 1
            elif unit == "reps":
                new_target = max(item.target - 2, 6)
            else:
                new_target = max(int(round(item.target * 0.8)), 5)

        out.append(
            {
                "exercise": item.exercise,
                "action": action,
                "current": {"sets": item.sets, "target": item.target},
                "suggested": {"sets": new_sets, "target": new_target},
                "completion": None if completion is None else round(completion, 2),
                "reasons": reasons,
                "requires_clinician_approval": True,
            }
        )
    return out


def apply(prescription: Prescription, suggestions: List[dict], accepted: List[str]) -> Prescription:
    """Returns a new prescription with the accepted suggestions (by exercise id) applied."""
    accepted_set = set(accepted)
    lookup = {s["exercise"]: s for s in suggestions}
    new = Prescription.from_dict(prescription.to_dict())
    for item in new.exercises:
        s = lookup.get(item.exercise)
        if s and item.exercise in accepted_set:
            item.sets = s["suggested"]["sets"]
            item.target = s["suggested"]["target"]
    return new
