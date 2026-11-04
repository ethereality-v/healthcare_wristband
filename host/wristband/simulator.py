"""A fake wristband that speaks the same protocol as the firmware.

Lets the app, dashboard and CV integration be developed and demoed without hardware.
`speed` > 1 runs faster than real time (used by the tests).
"""

from __future__ import annotations

import queue
import random
import threading
import time
from typing import Callable, Optional

from .catalog import load_catalog


class SimulatedBand:
    TICK_S = 0.05  # simulated seconds per step

    def __init__(
        self,
        emit: Callable[[dict], None],
        speed: float = 1.0,
        seed: Optional[int] = None,
        resting_hr: int = 72,
        effort_hr: int = 45,
        completion: float = 1.0,
        rep_period_s: float = 2.6,
        partial_rate: float = 0.05,
    ):
        self.emit = emit
        self.speed = max(speed, 0.01)
        self.rng = random.Random(seed)
        self.resting_hr = resting_hr
        self.effort_hr = effort_hr  # extra BPM while exercising
        self.completion = completion  # fraction of target the "patient" manages
        self.rep_period_s = rep_period_s
        self.partial_rate = partial_rate
        self.catalog = load_catalog()

        self._lock = threading.Lock()
        self._stop = threading.Event()
        # Messages leave through their own thread, never while holding _lock, so the app can
        # call command() from inside its message handler without deadlocking (like a real band).
        self._outbox: "queue.Queue[dict]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self.t = 0.0  # simulated seconds since boot
        self.hr = float(resting_hr)
        self.active = False
        self.exercise = ""
        self.unit = "reps"
        self.mode = "tilt"
        self.set = 0
        self.target = 0
        self.manage = 0
        self.count = 0
        self.partial = 0
        self.set_start = 0.0
        self.ready = False
        self.target_sent = False
        self.next_rep_at = 0.0
        self.rep_started = 0.0
        self.alert = False
        self.hr_max = 0
        self.rom_total = 0.0
        self.rep_ms_total = 0.0
        self._last_status = 0.0
        self._last_vitals = 0.0

    # ---------- lifecycle ----------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="sim-band", daemon=True)
        self._thread.start()
        threading.Thread(target=self._emit_loop, name="sim-band-out", daemon=True).start()
        self._send({"type": "hello", "device": "wristband-SIM", "fw": "sim", "accel": "simulated",
                    "calibrated": True, "pulse": True, "wifi": False, "exercises": len(self.catalog.wrist_ids())})

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                self.step(self.TICK_S)
            time.sleep(self.TICK_S / self.speed)

    def _send(self, msg: dict) -> None:
        self._outbox.put(msg)

    def _emit_loop(self) -> None:
        while not self._stop.is_set():
            try:
                msg = self._outbox.get(timeout=0.2)
            except queue.Empty:
                continue
            self.emit(msg)

    def _ms(self) -> int:
        return int(self.t * 1000)

    # ---------- commands (same as firmware) ----------

    def command(self, msg: dict) -> None:
        with self._lock:
            self._command(msg)

    def _command(self, msg: dict) -> None:
        cmd = msg.get("cmd")
        if cmd in ("ping", "hello"):
            self._send({"type": "hello", "device": "wristband-SIM", "fw": "sim", "pulse": True})
        elif cmd == "list":
            self._send({"type": "exercises", "ids": self.catalog.wrist_ids()})
        elif cmd == "start":
            ex_id = msg.get("exercise", "")
            if ex_id not in self.catalog or not self.catalog.get(ex_id).is_wrist:
                self._send({"type": "error", "msg": "unknown exercise", "exercise": ex_id})
                return
            if self.active:
                self._finish()
            ex = self.catalog.get(ex_id)
            self.active, self.exercise, self.unit, self.mode = True, ex_id, ex.unit, ex.mode or "tilt"
            self.set = int(msg.get("set", 1))
            self.target = int(msg.get("target", 0))
            self.hr_max = int(msg.get("hr_max", 0))
            self.count = self.partial = 0
            self.rom_total = self.rep_ms_total = 0.0
            self.set_start = self.t
            self.ready = False
            self.target_sent = False
            # how many the simulated patient will manage this set
            goal = self.target if self.target else 12
            self.manage = max(1, int(round(goal * self.completion + self.rng.choice([0, 0, 0, -1, 1]))))
            if self.completion >= 1.0:
                self.manage = max(self.manage, goal)
            self._send({"type": "started", "exercise": ex_id, "set": self.set, "target": self.target, "unit": self.unit})
        elif cmd == "stop":
            if self.active:
                self._finish()
        elif cmd == "alert":
            self.alert = msg.get("level") == "stop"
        elif cmd == "calibrate":
            self._send({"type": "calibrated", "offsets_mv": [1650, 1650, 850]})
        elif cmd == "raw":
            pass
        else:
            self._send({"type": "error", "msg": "unknown command", "cmd": cmd})

    def _finish(self) -> None:
        self._send({
            "type": "set_done", "exercise": self.exercise, "set": self.set, "unit": self.unit,
            "count": self.count, "partial": self.partial, "target": self.target,
            "duration_ms": int((self.t - self.set_start) * 1000),
            "active_ms": int(max(self.t - self.set_start - 1.5, 0) * 1000),
            "avg_rep_ms": round(self.rep_ms_total / self.count) if self.count else 0,
            "avg_rom_deg": round(self.rom_total / self.count, 1) if self.count and self.mode == "tilt" else 0,
            "peak_accel": round(self.rng.uniform(2, 6), 2),
        })
        self.active = False

    # ---------- simulation step ----------

    def step(self, dt: float) -> None:
        self.t += dt
        # heart rate drifts toward resting or exercise level
        goal = self.resting_hr + (self.effort_hr if self.active and self.ready else 0)
        tau = 25.0 if goal > self.hr else 45.0
        self.hr += (goal - self.hr) * dt / tau

        if self.active:
            elapsed = self.t - self.set_start
            if not self.ready and elapsed >= 1.5:
                self.ready = True
                self.next_rep_at = self.t + self._rep_time()
                self.rep_started = self.t
                self._send({"type": "ready", "exercise": self.exercise, "set": self.set})
            if self.ready:
                if self.mode == "hold":
                    self.count = int(elapsed - 1.5) if elapsed - 1.5 < self.manage else self.manage
                elif self.count < self.manage and self.t >= self.next_rep_at:
                    self._rep()
                if self.target and not self.target_sent and self.count >= self.target:
                    self.target_sent = True
                    self._send({"type": "target_reached", "exercise": self.exercise, "set": self.set, "count": self.count})

        if self.t - self._last_vitals >= 4.0:
            self._last_vitals = self.t
            hr = int(round(self.hr + self.rng.gauss(0, 2)))
            self._send({"type": "vitals", "hr": hr, "spo2": int(round(min(100, self.rng.gauss(97, 0.8)))),
                        "hr_valid": True, "spo2_valid": True, "contact": True,
                        "moving": self.active and self.ready, "t": self._ms()})
            if self.hr_max and hr > self.hr_max and not self.alert:
                self.alert = True
                self._send({"type": "alert", "level": "stop", "reason": "hr_above_max", "hr": hr, "hr_max": self.hr_max})

        if self.t - self._last_status >= 0.5:
            self._last_status = self.t
            self._send({"type": "status", "t": self._ms(),
                        "state": ("active" if self.ready else "waiting_still") if self.active else "idle",
                        "exercise": self.exercise if self.active else "", "set": self.set,
                        "count": self.count if self.active else 0, "partial": self.partial, "target": self.target,
                        "angle": 0.0, "moving": self.active and self.ready, "hr": int(self.hr), "spo2": 97,
                        "contact": True, "alert": self.alert, "clipped": False, "battery_v": -1})

    def _rep_time(self) -> float:
        return max(0.8, self.rng.gauss(self.rep_period_s, 0.3))

    def _rep(self) -> None:
        duration = self.t - self.rep_started
        self.rep_started = self.t
        self.next_rep_at = self.t + self._rep_time()
        if self.rng.random() < self.partial_rate:
            self.partial += 1
            return
        self.count += 1
        rom = round(self.rng.gauss(115, 6), 1) if self.mode == "tilt" else 0.0
        self.rom_total += rom
        self.rep_ms_total += duration * 1000
        self._send({"type": "rep", "exercise": self.exercise, "set": self.set, "rep": self.count,
                    "duration_ms": int(duration * 1000), "rom_deg": rom,
                    "peak_accel": round(self.rng.uniform(1.5, 5), 2), "t": self._ms()})
