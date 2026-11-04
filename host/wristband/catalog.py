"""Exercise catalog, loaded from shared/exercises.json (the same file the firmware table is built from)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = REPO_ROOT / "shared" / "exercises.json"

# Order of a session, from the CCCARE programming guidelines
SESSION_ORDER = ["warmup", "mobility", "squat_lunge", "push", "hinge", "pull", "carry", "core", "stretch", "cooldown"]
FUNCTIONAL_CATEGORIES = ["squat_lunge", "push", "hinge", "pull", "carry", "core"]


@dataclass(frozen=True)
class Exercise:
    id: str
    name: str
    category: str
    tracker: str  # "wrist" (band counts it), "camera" (CV coach), "timer" (warm-up / cool-down)
    mode: Optional[str] = None  # wrist only: "tilt", "motion", "hold"
    unit: str = "reps"
    top_deg: Optional[float] = None

    @property
    def is_wrist(self) -> bool:
        return self.tracker == "wrist"


class Catalog:
    def __init__(self, data: dict):
        self.categories: Dict[str, str] = {c["id"]: c["name"] for c in data["categories"]}
        self.exercises: Dict[str, Exercise] = {}
        for raw in data["exercises"]:
            ex = Exercise(
                id=raw["id"],
                name=raw["name"],
                category=raw["category"],
                tracker=raw["tracker"],
                mode=raw.get("mode"),
                unit=raw.get("unit", "seconds" if raw["tracker"] == "timer" else "reps"),
                top_deg=raw.get("top_deg"),
            )
            if ex.category not in self.categories:
                raise ValueError(f"exercise {ex.id} has unknown category {ex.category}")
            if ex.id in self.exercises:
                raise ValueError(f"duplicate exercise id {ex.id}")
            self.exercises[ex.id] = ex

    def get(self, exercise_id: str) -> Exercise:
        try:
            return self.exercises[exercise_id]
        except KeyError:
            raise KeyError(f"unknown exercise '{exercise_id}'") from None

    def __contains__(self, exercise_id: str) -> bool:
        return exercise_id in self.exercises

    def in_category(self, category: str, tracker: Optional[str] = None) -> List[Exercise]:
        return [
            e for e in self.exercises.values() if e.category == category and (tracker is None or e.tracker == tracker)
        ]

    def wrist_ids(self) -> List[str]:
        return [e.id for e in self.exercises.values() if e.is_wrist]

    def to_json(self) -> dict:
        return {
            "categories": self.categories,
            "exercises": [e.__dict__ for e in self.exercises.values()],
        }


@lru_cache(maxsize=1)
def load_catalog(path: Optional[str] = None) -> Catalog:
    p = Path(path) if path else CATALOG_PATH
    return Catalog(json.loads(p.read_text(encoding="utf-8")))
