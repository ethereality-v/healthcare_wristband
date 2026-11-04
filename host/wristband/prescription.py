"""Patient prescriptions and the session plan built from them.

Programming guidelines (CCCARE): cardio warm-up, 2 mobility exercises, one exercise for each
functional category, stretches, cardio cool-down. 10-20 reps and 1-2 sets per exercise.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import List, Optional

from .catalog import FUNCTIONAL_CATEGORIES, SESSION_ORDER, Catalog

TYPICAL_REPS = (10, 20)
TYPICAL_SETS = (1, 2)


@dataclass
class PrescribedExercise:
    exercise: str
    sets: int = 1
    target: int = 12          # reps, steps or seconds depending on the exercise's unit
    rest_s: int = 60
    top_deg: Optional[float] = None  # tilt exercises: patient-specific range of motion target
    notes: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "PrescribedExercise":
        return cls(
            exercise=d["exercise"],
            sets=int(d.get("sets", 1)),
            target=int(d.get("target", d.get("reps", 12))),
            rest_s=int(d.get("rest_s", 60)),
            top_deg=d.get("top_deg"),
            notes=d.get("notes", ""),
        )


@dataclass
class Prescription:
    exercises: List[PrescribedExercise] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Prescription":
        return cls(exercises=[PrescribedExercise.from_dict(e) for e in d.get("exercises", [])])

    def to_dict(self) -> dict:
        return {"exercises": [asdict(e) for e in self.exercises]}

    def validate(self, catalog: Catalog) -> List[str]:
        """Returns warnings. Raises ValueError for errors that make the plan unusable."""
        warnings: List[str] = []
        if not self.exercises:
            raise ValueError("prescription has no exercises")
        for e in self.exercises:
            if e.exercise not in catalog:
                raise ValueError(f"unknown exercise '{e.exercise}'")
            if not 1 <= e.sets <= 5:
                raise ValueError(f"{e.exercise}: sets must be 1-5")
            if not 1 <= e.target <= 600:
                raise ValueError(f"{e.exercise}: target must be 1-600")
            ex = catalog.get(e.exercise)
            if ex.unit == "reps" and not TYPICAL_REPS[0] <= e.target <= TYPICAL_REPS[1]:
                warnings.append(f"{ex.name}: {e.target} reps is outside the usual 10-20")
            if ex.tracker != "timer" and not TYPICAL_SETS[0] <= e.sets <= TYPICAL_SETS[1]:
                warnings.append(f"{ex.name}: {e.sets} sets is outside the usual 1-2")
        cats = [catalog.get(e.exercise).category for e in self.exercises]
        if cats.count("mobility") < 2:
            warnings.append("guidelines start with 2 mobility exercises")
        for c in FUNCTIONAL_CATEGORIES:
            if c not in cats:
                warnings.append(f"no {catalog.categories[c]} exercise")
        return warnings


@dataclass
class Step:
    """One set (or timed block) of the session."""

    index: int
    exercise: str
    name: str
    category: str
    tracker: str
    unit: str
    set: int
    sets: int
    target: int
    rest_s: int
    top_deg: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


def build_plan(prescription: Prescription, catalog: Catalog) -> List[Step]:
    """Expands the prescription into one step per set, in session order."""
    order = {c: i for i, c in enumerate(SESSION_ORDER)}
    # stable sort keeps the clinician's order inside each category
    items = sorted(prescription.exercises, key=lambda e: order.get(catalog.get(e.exercise).category, 99))
    steps: List[Step] = []
    for item in items:
        ex = catalog.get(item.exercise)
        for s in range(1, item.sets + 1):
            steps.append(
                Step(
                    index=len(steps),
                    exercise=ex.id,
                    name=ex.name,
                    category=ex.category,
                    tracker=ex.tracker,
                    unit=ex.unit,
                    set=s,
                    sets=item.sets,
                    target=item.target,
                    rest_s=item.rest_s,  # rest after every set, including before the next exercise
                    top_deg=item.top_deg,
                )
            )
    return steps


def default_prescription() -> Prescription:
    """A starting plan that follows the guidelines and uses wrist-trackable exercises where possible."""
    rows = [
        ("warmup_march", 1, 300, 0),
        ("arm_rainbow", 1, 10, 30),
        ("thoracic_rotation", 1, 10, 30),
        ("goblet_squat", 2, 10, 60),
        ("shoulder_press", 2, 10, 60),
        ("kettlebell_swing", 1, 12, 60),
        ("bicep_curl", 2, 12, 60),
        ("farmers_carry", 1, 40, 60),
        ("torso_rotation", 1, 12, 45),
        ("hamstring_stretch", 1, 30, 0),
        ("chest_doorway_stretch", 1, 30, 0),
        ("cooldown_walk", 1, 300, 0),
    ]
    return Prescription([PrescribedExercise(e, sets, target, rest) for e, sets, target, rest in rows])
