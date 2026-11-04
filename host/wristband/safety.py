"""Heart rate / SpO2 safety checks.

The target zone uses heart-rate reserve (Karvonen) at a moderate 40-70 % intensity, which is a
common range for clinical exercise programs, with age-predicted maximum HR from Tanaka
(208 - 0.7 x age). A clinician can override the limits per patient. For patients on
beta-blockers HR does not track effort, so HR-zone warnings are off and only absolute limits and
SpO2 apply. Use the RPE (Borg 6-20) rating instead.

These are screening flags for the instructor, not medical decisions.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional

OK, WARN, STOP = "ok", "warn", "stop"
_RANK = {OK: 0, WARN: 1, STOP: 2}

SPO2_WARN = 93
SPO2_STOP = 90
ABSOLUTE_HR_STOP = 180  # never exceeded for this population, regardless of zone settings


def predicted_hr_max(age: float) -> float:
    return 208.0 - 0.7 * age


@dataclass
class Limits:
    zone_low: int
    zone_high: int     # warn above this
    hr_stop: int       # STOP above this
    spo2_warn: int = SPO2_WARN
    spo2_stop: int = SPO2_STOP
    hr_zone_enabled: bool = True

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def limits_for(patient: dict) -> Limits:
    age = float(patient.get("age") or 65)
    rest = float(patient.get("resting_hr") or 70)
    hr_max = float(patient.get("hr_max") or predicted_hr_max(age))
    reserve = max(hr_max - rest, 20)
    zone_low = int(round(rest + 0.40 * reserve))
    zone_high = int(round(rest + 0.70 * reserve))
    hr_stop = int(patient.get("hr_stop") or min(round(rest + 0.85 * reserve), ABSOLUTE_HR_STOP))
    return Limits(
        zone_low=zone_low,
        zone_high=min(zone_high, hr_stop - 1),
        hr_stop=hr_stop,
        spo2_warn=int(patient.get("spo2_warn") or SPO2_WARN),
        spo2_stop=int(patient.get("spo2_stop") or SPO2_STOP),
        hr_zone_enabled=not bool(patient.get("beta_blocker")),
    )


@dataclass
class Assessment:
    level: str = OK
    reasons: List[str] = field(default_factory=list)

    def raise_to(self, level: str, reason: str) -> None:
        if _RANK[level] > _RANK[self.level]:
            self.level = level
        self.reasons.append(reason)

    def to_dict(self) -> dict:
        return {"level": self.level, "reasons": list(self.reasons)}


class VitalsMonitor:
    """Turns the stream of band vitals into ok / warn / stop.

    Wrist PPG is noisy during movement, so a single reading taken while moving can only cause a
    warning. STOP needs one reading taken while still, or two in a row.
    """

    def __init__(self, limits: Limits):
        self.limits = limits
        self.recent: Deque[dict] = deque(maxlen=6)
        self.current = Assessment()
        self.latest_hr: Optional[int] = None
        self.latest_spo2: Optional[int] = None

    def _level_of(self, v: dict) -> Assessment:
        a = Assessment()
        lim = self.limits
        hr = v.get("hr") if v.get("hr_valid") else None
        spo2 = v.get("spo2") if v.get("spo2_valid") else None
        if hr is not None:
            if hr > lim.hr_stop or hr > ABSOLUTE_HR_STOP:
                a.raise_to(STOP, f"heart rate {hr} bpm is above the stop limit {lim.hr_stop}")
            elif lim.hr_zone_enabled and hr > lim.zone_high:
                a.raise_to(WARN, f"heart rate {hr} bpm is above the target zone ({lim.zone_low}-{lim.zone_high})")
        if spo2 is not None:
            if spo2 < lim.spo2_stop:
                a.raise_to(STOP, f"SpO2 {spo2}% is below {lim.spo2_stop}%")
            elif spo2 < lim.spo2_warn:
                a.raise_to(WARN, f"SpO2 {spo2}% is below {lim.spo2_warn}%")
        return a

    def add(self, vitals: dict) -> Assessment:
        if vitals.get("hr_valid"):
            self.latest_hr = vitals.get("hr")
        if vitals.get("spo2_valid"):
            self.latest_spo2 = vitals.get("spo2")
        if not (vitals.get("hr_valid") or vitals.get("spo2_valid")):
            return self.current  # nothing usable (no skin contact / bad reading)

        a = self._level_of(vitals)
        previous = self._level_of(self.recent[-1]) if self.recent else Assessment()
        self.recent.append(vitals)

        if a.level == STOP and vitals.get("moving") and previous.level != STOP:
            a.level = WARN
            a.reasons = [r + " (while moving, re-checking)" for r in a.reasons]
        self.current = a
        return a

    def hr_in_zone_fraction(self, readings: List[dict]) -> Optional[float]:
        hrs = [r["hr"] for r in readings if r.get("hr_valid")]
        if not hrs:
            return None
        inside = sum(1 for h in hrs if self.limits.zone_low <= h <= self.limits.zone_high)
        return inside / len(hrs)
