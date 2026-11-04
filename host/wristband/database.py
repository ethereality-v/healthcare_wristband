"""JSON database: patients, prescriptions and sessions in one file (default data/database.json).

Writes go to a temporary file and are then renamed over the old one, so a crash or power
loss can never leave a half-written database. The file holds health data: it is git-ignored.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .prescription import Prescription, default_prescription

SCHEMA_VERSION = 1


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._data = self._load()

    # ---------- file handling ----------

    def _load(self) -> dict:
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("patients", {})
            data.setdefault("sessions", [])
            return data
        return {"version": SCHEMA_VERSION, "created": now_iso(), "patients": {}, "sessions": []}

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".db-", suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, indent=2)
                os.replace(tmp, self.path)
            except BaseException:
                if os.path.exists(tmp):
                    os.remove(tmp)
                raise

    # ---------- patients ----------

    def patients(self) -> List[dict]:
        with self._lock:
            return [deepcopy(p) for p in self._data["patients"].values()]

    def patient(self, patient_id: str) -> Optional[dict]:
        with self._lock:
            p = self._data["patients"].get(patient_id)
            return deepcopy(p) if p else None

    def upsert_patient(self, patient: dict) -> dict:
        if not patient.get("id"):
            raise ValueError("patient needs an id")
        with self._lock:
            existing = self._data["patients"].get(patient["id"], {})
            merged = {**existing, **patient}
            merged.setdefault("created", now_iso())
            merged.setdefault("prescription", default_prescription().to_dict())
            merged["updated"] = now_iso()
            self._data["patients"][patient["id"]] = merged
            self.save()
            return deepcopy(merged)

    def set_prescription(self, patient_id: str, prescription: Prescription, note: str = "") -> dict:
        with self._lock:
            p = self._data["patients"].get(patient_id)
            if p is None:
                raise KeyError(patient_id)
            history = p.setdefault("prescription_history", [])
            if "prescription" in p:
                history.append({"until": now_iso(), "prescription": p["prescription"], "note": note})
            p["prescription"] = prescription.to_dict()
            p["updated"] = now_iso()
            self.save()
            return deepcopy(p)

    # ---------- sessions ----------

    def new_session(self, patient_id: str, source: str, plan: List[dict]) -> dict:
        session = {
            "id": datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4],
            "patient_id": patient_id,
            "source": source,
            "started_at": now_iso(),
            "ended_at": None,
            "status": "running",
            "plan": plan,
            "exercises": [],
            "vitals": [],
            "alerts": [],
            "cv_events": [],
            "rpe": None,
            "suggestions": [],
        }
        with self._lock:
            self._data["sessions"].append(session)
            self.save()
        return session

    def update_session(self, session: dict) -> None:
        """Replaces the stored session with the same id (the runner owns the live copy)."""
        with self._lock:
            for i, s in enumerate(self._data["sessions"]):
                if s["id"] == session["id"]:
                    self._data["sessions"][i] = deepcopy(session)
                    break
            else:
                self._data["sessions"].append(deepcopy(session))
            self.save()

    def session(self, session_id: str) -> Optional[dict]:
        with self._lock:
            for s in self._data["sessions"]:
                if s["id"] == session_id:
                    return deepcopy(s)
        return None

    def sessions(self, patient_id: Optional[str] = None) -> List[dict]:
        with self._lock:
            return [deepcopy(s) for s in self._data["sessions"] if patient_id is None or s["patient_id"] == patient_id]

    def session_summaries(self, patient_id: Optional[str] = None) -> List[dict]:
        out = []
        for s in self.sessions(patient_id):
            done = sum(min(st.get("count", 0), st.get("target", 0)) for e in s["exercises"] for st in e.get("sets", []))
            target = sum(st.get("target", 0) for e in s["exercises"] for st in e.get("sets", []))
            hrs = [v["hr"] for v in s["vitals"] if v.get("hr_valid")]
            out.append(
                {
                    "id": s["id"],
                    "patient_id": s["patient_id"],
                    "started_at": s["started_at"],
                    "ended_at": s["ended_at"],
                    "status": s["status"],
                    "exercises": len(s["exercises"]),
                    "completion": round(done / target, 2) if target else None,
                    "avg_hr": round(sum(hrs) / len(hrs)) if hrs else None,
                    "max_hr": max(hrs) if hrs else None,
                    "stops": sum(1 for a in s["alerts"] if a.get("level") == "stop"),
                    "rpe": s.get("rpe"),
                }
            )
        return out
