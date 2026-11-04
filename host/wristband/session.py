"""Runs an exercise session: walks the plan set by set, talks to the band, records everything.

Phases
    idle            no session
    ready           waiting for "start set" (or auto-start)
    waiting_still   band asked the patient to hold the start position
    running         set in progress (band reps, CV reps, or a timer)
    stopping        stop sent to the band, waiting for its set summary
    resting         rest timer between sets
    alert           safety STOP: set ended, instructor must clear the alert
    finished        session over, dosage suggestions ready

Band messages arrive on the transport thread, dashboard/CV requests on HTTP threads and
timers on the ticker thread. Everything goes through one lock.
"""

from __future__ import annotations

import logging
import threading
import time
from copy import deepcopy
from typing import Callable, List, Optional

from . import dosage
from .catalog import Catalog
from .database import Database, now_iso
from .prescription import Prescription, Step, build_plan
from .safety import OK, STOP, WARN, VitalsMonitor, limits_for
from .transport import Transport

log = logging.getLogger(__name__)

SET_DONE_TIMEOUT_S = 3.0


class SessionError(Exception):
    pass


class SessionRunner:
    def __init__(
        self,
        db: Database,
        catalog: Catalog,
        transport: Transport,
        auto_advance: bool = True,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.db = db
        self.catalog = catalog
        self.transport = transport
        self.auto_advance = auto_advance
        self.clock = clock
        self.lock = threading.RLock()

        self.session: Optional[dict] = None
        self.patient: Optional[dict] = None
        self.prescription: Optional[Prescription] = None
        self.plan: List[Step] = []
        self.step_idx = 0
        self.phase = "idle"
        self.live: dict = {}
        self.rest_until = 0.0
        self.stop_sent_at = 0.0
        self.monitor: Optional[VitalsMonitor] = None
        self.alert = {"level": OK, "reasons": [], "since": None}
        self.band = {"device": None, "status": None, "last_message": None, "hello": None}
        self.events: List[dict] = []  # recent log lines for the dashboard
        self.warnings: List[str] = []

    # ---------- helpers ----------

    @property
    def step(self) -> Optional[Step]:
        if 0 <= self.step_idx < len(self.plan):
            return self.plan[self.step_idx]
        return None

    def _log(self, text: str, level: str = "info") -> None:
        self.events.append({"time": now_iso(), "level": level, "text": text})
        del self.events[:-50]
        getattr(log, "warning" if level == "warn" else "info")(text)

    def _send(self, msg: dict) -> None:
        try:
            self.transport.send(msg)
        except Exception as e:
            self._log(f"could not send to band: {e}", "warn")

    def _exercise_record(self, step: Step) -> dict:
        for rec in self.session["exercises"]:
            if rec["exercise"] == step.exercise:
                return rec
        rec = {
            "exercise": step.exercise,
            "name": step.name,
            "category": step.category,
            "tracker": step.tracker,
            "unit": step.unit,
            "sets": [],
            "vitals": [],
            "cv": [],
        }
        self.session["exercises"].append(rec)
        return rec

    def _save(self) -> None:
        if self.session:
            self.db.update_session(self.session)

    # ---------- session control (dashboard) ----------

    def start_session(self, patient_id: str) -> dict:
        with self.lock:
            if self.session and self.phase != "finished":
                raise SessionError("a session is already running")
            patient = self.db.patient(patient_id)
            if patient is None:
                raise SessionError(f"unknown patient '{patient_id}'")
            prescription = Prescription.from_dict(patient.get("prescription", {}))
            try:
                self.warnings = prescription.validate(self.catalog)
            except ValueError as e:
                raise SessionError(f"invalid prescription: {e}") from None
            self.patient = patient
            self.prescription = prescription
            self.plan = build_plan(prescription, self.catalog)
            self.monitor = VitalsMonitor(limits_for(patient))
            self.session = self.db.new_session(patient_id, self.transport.describe(), [s.to_dict() for s in self.plan])
            self.session["limits"] = self.monitor.limits.to_dict()
            self.step_idx = 0
            self.alert = {"level": OK, "reasons": [], "since": None}
            self.events = []
            self._log(f"session started for {patient.get('name', patient_id)}: {len(self.plan)} sets")
            self.phase = "ready"
            if self.auto_advance:
                self._begin_step()
            self._save()
            return self.snapshot()

    def start_set(self) -> None:
        with self.lock:
            if self.phase not in ("ready", "resting"):
                raise SessionError(f"cannot start a set while {self.phase}")
            self._begin_step()

    def stop_set(self) -> None:
        with self.lock:
            if self.phase not in ("waiting_still", "running"):
                raise SessionError("no set is running")
            self._request_stop()

    def skip(self) -> None:
        with self.lock:
            step = self.step
            if step is None or self.phase in ("idle", "finished"):
                raise SessionError("nothing to skip")
            if self.phase in ("waiting_still", "running", "stopping") and step.tracker == "wrist":
                self._send({"cmd": "stop"})
            self._record_set(step, {"count": self.live.get("count", 0), "skipped": True, "source": "manual"})
            self._log(f"skipped {step.name} set {step.set}")
            self._advance(rest=False)

    def complete_manual(self, count: int) -> None:
        """Instructor enters the count (camera exercises when CV isn't running, or corrections)."""
        with self.lock:
            step = self.step
            if step is None or self.phase not in ("ready", "waiting_still", "running", "stopping"):
                raise SessionError("no current set")
            if step.tracker == "wrist" and self.phase in ("waiting_still", "running", "stopping"):
                self._send({"cmd": "stop"})
            self._record_set(step, {**self._live_summary(), "count": int(count), "source": "manual"})
            self._advance()

    def clear_alert(self) -> None:
        with self.lock:
            self.alert = {"level": OK, "reasons": [], "since": None}
            self._send({"cmd": "alert", "level": "none"})
            self._log("alert cleared by instructor")
            if self.phase == "alert":
                if self.step:
                    self.phase = "ready"
                else:
                    self._finish("completed")

    def end_session(self, status: str = "completed") -> dict:
        with self.lock:
            if not self.session:
                raise SessionError("no session")
            if self.phase in ("waiting_still", "running", "stopping") and self.step and self.step.tracker == "wrist":
                self._send({"cmd": "stop"})
                self._record_set(self.step, {**self._live_summary(), "source": "band", "ended_early": True})
            self._finish(status)
            return self.snapshot()

    def set_rpe(self, rpe: int) -> None:
        with self.lock:
            if not self.session:
                raise SessionError("no session")
            if not 6 <= int(rpe) <= 20:
                raise SessionError("RPE uses the Borg 6-20 scale")
            self.session["rpe"] = int(rpe)
            if self.phase == "finished":
                self.session["suggestions"] = self._suggestions()
            self._save()

    # ---------- step flow ----------

    def _begin_step(self) -> None:
        step = self.step
        if step is None:
            self._finish("completed")
            return
        self.live = {"count": 0, "partial": 0, "reps": [], "started": self.clock(), "cv_count": None,
                     "form_scores": [], "feedback": []}
        if step.tracker == "wrist":
            cmd = {"cmd": "start", "exercise": step.exercise, "set": step.set, "target": step.target,
                   "hr_max": self.monitor.limits.hr_stop}
            if step.top_deg:
                cmd["top_deg"] = step.top_deg
            self._send(cmd)
            self.phase = "waiting_still"
            self._log(f"{step.name} set {step.set}/{step.sets}: hold your starting position")
        else:
            self.phase = "running"
            how = "timer" if step.tracker == "timer" else "camera"
            self._log(f"{step.name} set {step.set}/{step.sets} started ({how})")

    def _request_stop(self) -> None:
        step = self.step
        if step and step.tracker == "wrist":
            self._send({"cmd": "stop"})
            self.phase = "stopping"
            self.stop_sent_at = self.clock()
        elif step:
            self._record_set(step, {**self._live_summary(), "source": step.tracker})
            self._advance()

    def _live_summary(self) -> dict:
        reps = self.live.get("reps", [])
        roms = [r["rom_deg"] for r in reps if r.get("rom_deg")]
        durations = [r["duration_ms"] for r in reps if r.get("duration_ms")]
        return {
            "count": self.live.get("count", 0),
            "partial": self.live.get("partial", 0),
            "avg_rep_ms": round(sum(durations) / len(durations)) if durations else 0,
            "avg_rom_deg": round(sum(roms) / len(roms), 1) if roms else 0,
            "duration_ms": int((self.clock() - self.live.get("started", self.clock())) * 1000),
        }

    def _record_set(self, step: Step, result: dict) -> None:
        rec = self._exercise_record(step)
        if any(s["set"] == step.set for s in rec["sets"]):
            return  # already recorded (e.g. late set_done after a manual entry)
        entry = {
            "set": step.set,
            "target": step.target,
            "unit": step.unit,
            "count": int(result.get("count", 0)),
            "partial": int(result.get("partial", 0)),
            "duration_ms": result.get("duration_ms"),
            "active_ms": result.get("active_ms"),
            "avg_rep_ms": result.get("avg_rep_ms"),
            "avg_rom_deg": result.get("avg_rom_deg"),
            "peak_accel": result.get("peak_accel"),
            "reps": list(self.live.get("reps", [])),
            "source": result.get("source", "band"),
            "skipped": bool(result.get("skipped", False)),
            "stopped_by_alert": bool(result.get("stopped_by_alert", False)),
            "ended_early": bool(result.get("ended_early", False)),
            "finished_at": now_iso(),
        }
        # Wrist + camera cross-check ("combining the IMU with computer vision")
        if self.live.get("cv_count") is not None:
            entry["cv_count"] = self.live["cv_count"]
        if self.live.get("form_scores"):
            entry["form_score"] = round(sum(self.live["form_scores"]) / len(self.live["form_scores"]), 2)
        if self.live.get("feedback"):
            entry["cv_feedback"] = self.live["feedback"][-5:]
        entry["completed"] = entry["count"] >= step.target and not entry["skipped"]
        rec["sets"].append(entry)
        self._log(f"{step.name} set {step.set}: {entry['count']}/{step.target} {step.unit}")
        self._save()

    def _advance(self, rest: bool = True) -> None:
        step = self.step
        self.step_idx += 1
        self.live = {}
        if self.step is None:
            self._finish("completed")
            return
        if rest and step is not None and step.rest_s > 0:
            self.phase = "resting"
            self.rest_until = self.clock() + step.rest_s
        else:
            self.phase = "ready"
            if self.auto_advance:
                self._begin_step()

    def _finish(self, status: str) -> None:
        self.phase = "finished"
        self.session["status"] = status
        self.session["ended_at"] = now_iso()
        self.session["suggestions"] = self._suggestions()
        self._log(f"session {status}")
        self._save()

    def _suggestions(self) -> list:
        return dosage.suggest(self.session, self.prescription, self.monitor.limits.to_dict() if self.monitor else None)

    def _raise_alert(self, level: str, reasons: List[str], source: str) -> None:
        step = self.step
        changed = level != self.alert["level"]
        self.alert = {"level": level, "reasons": reasons, "since": now_iso()}
        if self.session is not None:
            self.session["alerts"].append({
                "time": now_iso(), "level": level, "reasons": reasons, "source": source,
                "exercise": step.exercise if step else None, "set": step.set if step else None,
            })
        if changed or level == STOP:
            self._send({"cmd": "alert", "level": level})
        self._log("; ".join(reasons), "warn" if level != OK else "info")
        if level == STOP and step and self.phase in ("waiting_still", "running", "stopping"):
            # End the set right away. The instructor decides when to continue.
            if step.tracker == "wrist":
                self._send({"cmd": "stop"})
            self._record_set(step, {**self._live_summary(), "source": step.tracker, "stopped_by_alert": True})
            self.step_idx += 1
            self.live = {}
            self.phase = "alert"
        elif level == STOP and self.phase in ("ready", "resting"):
            self.phase = "alert"

    # ---------- band messages (transport thread) ----------

    def handle_band(self, msg: dict) -> None:
        with self.lock:
            kind = msg.get("type")
            self.band["last_message"] = now_iso()
            if kind == "hello":
                self.band["device"] = msg.get("device")
                self.band["hello"] = msg
                if msg.get("calibrated") is False:
                    self._log("band accelerometer is not calibrated (lay flat, hold BOOT 2 s)", "warn")
            elif kind == "status":
                self.band["status"] = msg
                step = self.step
                if (self.session and step and msg.get("exercise") == step.exercise
                        and self.phase in ("waiting_still", "running", "stopping")):
                    # hold exercises report seconds only through status; partial reps too
                    self.live["count"] = max(self.live.get("count", 0), int(msg.get("count", 0)))
                    self.live["partial"] = int(msg.get("partial", 0))
            elif kind in ("error", "log", "text"):
                text = msg.get("msg") or msg.get("text") or str(msg)
                self._log(f"band: {text}", "warn" if kind == "error" else "info")
            elif kind == "vitals":
                self._on_vitals(msg)
            elif kind == "alert":
                if msg.get("level") == "stop" and self.alert["level"] != STOP:
                    self._raise_alert(STOP, [f"band: heart rate {msg.get('hr')} above {msg.get('hr_max')}"], "band")
            elif self.session is None or self.step is None:
                return
            elif kind == "ready":
                if self.phase == "waiting_still" and msg.get("exercise") == self.step.exercise:
                    self.phase = "running"
                    self._log(f"{self.step.name}: go!")
            elif kind == "rep":
                if msg.get("exercise") == self.step.exercise and self.phase in ("running", "waiting_still", "stopping"):
                    self.phase = "running" if self.phase == "waiting_still" else self.phase
                    self.live.setdefault("reps", []).append({k: msg.get(k) for k in ("rep", "duration_ms", "rom_deg", "peak_accel")})
                    self.live["count"] = int(msg.get("rep", self.live.get("count", 0) + 1))
            elif kind == "target_reached":
                if msg.get("exercise") == self.step.exercise and self.phase == "running":
                    self.live["count"] = max(self.live.get("count", 0), int(msg.get("count", 0)))
                    self._request_stop()
            elif kind == "set_done":
                if msg.get("exercise") == self.step.exercise and self.phase in ("running", "waiting_still", "stopping"):
                    self.live["count"] = int(msg.get("count", self.live.get("count", 0)))
                    self._record_set(self.step, {**msg, "source": "band"})
                    self._advance()

    def _on_vitals(self, msg: dict) -> None:
        entry = {k: msg.get(k) for k in ("hr", "spo2", "hr_valid", "spo2_valid", "contact", "moving")}
        entry["time"] = now_iso()
        step = self.step
        if self.session is not None:
            entry["exercise"] = step.exercise if step and self.phase in ("running", "waiting_still") else None
            self.session["vitals"].append(entry)
            if step and entry["exercise"]:
                self._exercise_record(step)["vitals"].append(entry)
        if self.monitor is None:
            return
        a = self.monitor.add(msg)
        if a.level == STOP and self.alert["level"] != STOP:
            self._raise_alert(STOP, a.reasons, "vitals")
        elif a.level == WARN and self.alert["level"] == OK:
            self._raise_alert(WARN, a.reasons, "vitals")
        elif a.level == OK and self.alert["level"] == WARN:
            self.alert = {"level": OK, "reasons": [], "since": None}
            self._send({"cmd": "alert", "level": "none"})

    # ---------- computer vision (HTTP thread) ----------

    def handle_cv(self, event: dict) -> dict:
        """Result from the CV coach. See docs/protocol.md for the fields."""
        with self.lock:
            if not self.session:
                raise SessionError("no session running")
            ex_id = event.get("exercise")
            if ex_id and ex_id not in self.catalog:
                raise SessionError(f"unknown exercise '{ex_id}'")
            record = {"time": now_iso(), **event}
            self.session["cv_events"].append(record)
            step = self.step
            matched = bool(step and ex_id == step.exercise and self.phase in ("waiting_still", "running", "stopping"))
            if step and ex_id == step.exercise:
                self._exercise_record(step)["cv"].append(record)
            if matched:
                if "form_score" in event:
                    self.live.setdefault("form_scores", []).append(float(event["form_score"]))
                if event.get("feedback"):
                    self.live.setdefault("feedback", []).append(event["feedback"])
                reps = event.get("reps")
                if reps is not None:
                    if step.tracker == "camera":
                        self.live["count"] = int(reps)
                        if event.get("rom_deg") is not None:
                            self.live.setdefault("reps", []).append({"rep": int(reps), "rom_deg": event["rom_deg"]})
                    else:
                        self.live["cv_count"] = int(reps)  # cross-check only; the band counts wrist exercises
                if step.tracker == "camera" and (
                    event.get("event") == "set_done" or self.live.get("count", 0) >= step.target
                ):
                    self._record_set(step, {**self._live_summary(), "source": "camera"})
                    self._advance()
            return {"matched_current_set": matched, "current_exercise": step.exercise if step else None}

    # ---------- timers (ticker thread) ----------

    def tick(self) -> None:
        with self.lock:
            now = self.clock()
            step = self.step
            if self.phase == "resting" and now >= self.rest_until:
                self.phase = "ready"
                if self.auto_advance:
                    self._begin_step()
            elif self.phase == "running" and step and step.tracker == "timer":
                self.live["count"] = int(now - self.live["started"])
                if self.live["count"] >= step.target:
                    self._record_set(step, {**self._live_summary(), "source": "timer"})
                    self._advance()
            elif self.phase == "stopping" and now - self.stop_sent_at > SET_DONE_TIMEOUT_S and step:
                self._log("band didn't confirm the set; using the live count", "warn")
                self._record_set(step, {**self._live_summary(), "source": "band"})
                self._advance()

    # ---------- dashboard state ----------

    def snapshot(self) -> dict:
        with self.lock:
            step = self.step
            limits = self.monitor.limits.to_dict() if self.monitor else None
            status = self.band.get("status") or {}
            return deepcopy({
                "phase": self.phase,
                "session_id": self.session["id"] if self.session else None,
                "patient": {k: self.patient.get(k) for k in ("id", "name", "age")} if self.patient else None,
                "step_index": self.step_idx,
                "step": step.to_dict() if step else None,
                "plan": [
                    {**s.to_dict(), "done": i < self.step_idx} for i, s in enumerate(self.plan)
                ],
                "count": self.live.get("count", 0) if self.live else 0,
                "partial": self.live.get("partial", 0) if self.live else 0,
                "cv_count": self.live.get("cv_count") if self.live else None,
                "last_rep": (self.live.get("reps") or [None])[-1] if self.live else None,
                "rest_remaining": max(0, round(self.rest_until - self.clock())) if self.phase == "resting" else 0,
                "alert": self.alert,
                "limits": limits,
                "vitals": {
                    "hr": self.monitor.latest_hr if self.monitor else (status.get("hr") or None),
                    "spo2": self.monitor.latest_spo2 if self.monitor else (status.get("spo2") or None),
                    "contact": status.get("contact"),
                },
                "band": {
                    "connected": self.transport.connected,
                    "link": self.transport.describe(),
                    "device": self.band.get("device"),
                    "state": status.get("state"),
                    "angle": status.get("angle"),
                    "battery_v": status.get("battery_v"),
                    "calibrated": (self.band.get("hello") or {}).get("calibrated"),
                },
                "warnings": self.warnings,
                "suggestions": self.session.get("suggestions", []) if self.session else [],
                "rpe": self.session.get("rpe") if self.session else None,
                "events": self.events[-15:],
            })
