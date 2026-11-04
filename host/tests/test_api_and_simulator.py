"""REST API (direct dispatch and real HTTP) and an end-to-end run against the simulated band."""

import json
import threading
import time
import urllib.error
import urllib.request

from wristband.server import build, serve, start_ticker
from wristband.transport import SimulatedTransport, parse_line

SHORT_RX = {"exercises": [
    {"exercise": "arm_rainbow", "sets": 1, "target": 3, "rest_s": 1},
    {"exercise": "bicep_curl", "sets": 2, "target": 3, "rest_s": 1},
    {"exercise": "push_up", "sets": 1, "target": 2, "rest_s": 0},
]}


def test_parse_line():
    assert parse_line('{"type":"rep","rep":1}') == {"type": "rep", "rep": 1}
    assert parse_line("ets Jul 29 2019 boot") == {"type": "text", "text": "ets Jul 29 2019 boot"}
    assert parse_line("   ") is None
    assert parse_line("{broken")["type"] == "text"


def test_api_dispatch(tmp_path, transport):
    app = build(str(tmp_path / "db.json"), transport)
    status, p = app.dispatch("POST", "/api/patients", {}, {"id": "A1", "name": "Ann", "age": 72, "prescription": SHORT_RX,
                                                         "evil_field": "ignored"})
    assert status == 200 and "evil_field" not in p
    status, p = app.dispatch("GET", "/api/patients/A1", {}, {})
    assert status == 200 and p["limits"]["hr_stop"] > p["limits"]["zone_high"]
    assert app.dispatch("GET", "/api/patients/none", {}, {})[0] == 404
    assert app.dispatch("POST", "/api/cv", {}, {"exercise": "push_up", "reps": 1})[0] == 409  # no session
    assert app.dispatch("POST", "/api/session/start", {}, {})[0] == 400
    status, state = app.dispatch("POST", "/api/session/start", {}, {"patient_id": "A1"})
    assert status == 200 and state["phase"] == "waiting_still"
    assert app.dispatch("POST", "/api/session/start", {}, {"patient_id": "A1"})[0] == 409
    assert app.dispatch("POST", "/api/patients", {}, {"id": "B", "prescription": {"exercises": [{"exercise": "nope"}]}})[0] == 400
    assert app.dispatch("GET", "/api/nothing", {}, {})[0] == 404
    assert app.dispatch("POST", "/api/band/ping", {}, {})[1] == {"sent": {"cmd": "ping"}}
    assert {"cmd": "ping"} in transport.sent


def http(base, method, path, body=None):
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.status, json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def wait_for(predicate, timeout=40.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_end_to_end_with_simulated_band(tmp_path):
    transport = SimulatedTransport(speed=40, seed=3, partial_rate=0.0)
    app = build(str(tmp_path / "db.json"), transport)
    httpd = serve(app, "127.0.0.1", 0)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    stop = threading.Event()
    start_ticker(app.runner, stop, interval=0.02)
    try:
        # dashboard page is served
        with urllib.request.urlopen(base + "/", timeout=5) as res:
            assert b"Wristband Coach" in res.read()

        assert http(base, "POST", "/api/patients", {"id": "S1", "name": "Sim", "age": 66, "prescription": SHORT_RX})[0] == 200
        status, state = http(base, "POST", "/api/session/start", {"patient_id": "S1"})
        assert status == 200, state

        # the simulated band counts the wrist exercises by itself
        assert wait_for(lambda: app.runner.step and app.runner.step.exercise == "push_up"), app.runner.snapshot()

        # the "CV coach" counts the push-ups through the public API
        assert wait_for(lambda: app.runner.phase == "running")
        status, out = http(base, "POST", "/api/cv", {"exercise": "push_up", "event": "rep", "reps": 1, "form_score": 0.9})
        assert status == 200 and out["matched_current_set"]
        http(base, "POST", "/api/cv", {"exercise": "push_up", "event": "set_done", "reps": 2, "form_score": 0.8})
        assert wait_for(lambda: app.runner.phase == "finished")

        status, state = http(base, "GET", "/api/state")
        assert state["phase"] == "finished" and state["suggestions"]
        assert http(base, "POST", "/api/rpe", {"rpe": 11})[0] == 200

        sid = state["session_id"]
        status, session = http(base, "GET", f"/api/sessions/{sid}")
        counts = {e["exercise"]: [s["count"] for s in e["sets"]] for e in session["exercises"]}
        assert counts == {"arm_rainbow": [3], "bicep_curl": [3, 3], "push_up": [2]}
        assert session["vitals"], "simulated vitals were logged"

        # clinician accepts the suggestions
        accept = [s["exercise"] for s in session["suggestions"] if s["action"] == "progress"]
        status, out = http(base, "POST", "/api/patients/S1/prescription", {"accept": accept, "session_id": sid})
        assert status == 200
        new_targets = {e["exercise"]: e["target"] for e in out["patient"]["prescription"]["exercises"]}
        for ex in accept:
            assert new_targets[ex] > {e["exercise"]: e["target"] for e in SHORT_RX["exercises"]}[ex]

        status, rows = http(base, "GET", "/api/sessions?patient=S1")
        assert rows[0]["completion"] == 1.0 and rows[0]["rpe"] == 11
    finally:
        stop.set()
        httpd.shutdown()
        transport.close()
