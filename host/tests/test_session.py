"""Session runner driven with hand-written band messages (no threads, fake clock)."""

import pytest

from wristband.session import SET_DONE_TIMEOUT_S, SessionError

CURLS_THEN_PUSHUPS = [
    {"exercise": "bicep_curl", "sets": 2, "target": 3, "rest_s": 30},
    {"exercise": "dead_bug", "sets": 1, "target": 5, "rest_s": 0},
]


def do_reps(runner, exercise, n, set_no=1):
    for i in range(1, n + 1):
        runner.handle_band({"type": "rep", "exercise": exercise, "set": set_no, "rep": i, "duration_ms": 2000,
                            "rom_deg": 110.0 + i, "peak_accel": 3.0})


def test_full_session_flow(make_runner, transport, clock, db):
    r = make_runner(CURLS_THEN_PUSHUPS)
    r.start_session("T1")
    start = transport.cmds("start")[-1]
    assert start["exercise"] == "bicep_curl" and start["target"] == 3 and start["set"] == 1
    assert start["hr_max"] == r.monitor.limits.hr_stop
    assert r.phase == "waiting_still"

    r.handle_band({"type": "ready", "exercise": "bicep_curl", "set": 1})
    assert r.phase == "running"
    do_reps(r, "bicep_curl", 3)
    assert r.snapshot()["count"] == 3
    r.handle_band({"type": "target_reached", "exercise": "bicep_curl", "set": 1, "count": 3})
    assert transport.cmds("stop"), "app stops the set when the target is reached"
    assert r.phase == "stopping"
    r.handle_band({"type": "set_done", "exercise": "bicep_curl", "set": 1, "count": 3, "partial": 1,
                   "avg_rep_ms": 2000, "avg_rom_deg": 112.0, "duration_ms": 9000})
    assert r.phase == "resting"
    assert r.snapshot()["rest_remaining"] == 30

    clock.advance(31)
    r.tick()
    assert r.phase == "waiting_still" and transport.cmds("start")[-1]["set"] == 2
    r.handle_band({"type": "ready", "exercise": "bicep_curl", "set": 2})
    do_reps(r, "bicep_curl", 3, 2)
    r.handle_band({"type": "set_done", "exercise": "bicep_curl", "set": 2, "count": 3})
    assert r.phase == "resting"
    clock.advance(31)
    r.tick()
    # camera exercise: nothing is sent to the band, the CV coach counts it
    assert r.phase == "running" and r.step.exercise == "dead_bug"

    out = r.handle_cv({"exercise": "dead_bug", "event": "rep", "reps": 4, "form_score": 0.8})
    assert out["matched_current_set"] is True and r.phase == "running"
    r.handle_cv({"exercise": "dead_bug", "event": "rep", "reps": 5, "form_score": 0.9, "feedback": "keep hips level"})
    assert r.phase == "finished"

    session = db.session(r.session["id"])
    assert session["status"] == "completed"
    curls = next(e for e in session["exercises"] if e["exercise"] == "bicep_curl")
    assert [s["count"] for s in curls["sets"]] == [3, 3]
    assert curls["sets"][0]["partial"] == 1 and len(curls["sets"][0]["reps"]) == 3
    push = next(e for e in session["exercises"] if e["exercise"] == "dead_bug")
    assert push["sets"][0]["source"] == "camera" and push["sets"][0]["form_score"] == 0.85
    assert {s["exercise"] for s in session["suggestions"]} == {"bicep_curl", "dead_bug"}

    r.set_rpe(12)
    assert db.session(r.session["id"])["rpe"] == 12


def test_safety_stop_ends_set_and_waits_for_instructor(make_runner, transport):
    r = make_runner(CURLS_THEN_PUSHUPS)
    r.start_session("T1")
    r.handle_band({"type": "ready", "exercise": "bicep_curl", "set": 1})
    do_reps(r, "bicep_curl", 1)
    r.handle_band({"type": "vitals", "hr": 190, "spo2": 97, "hr_valid": True, "spo2_valid": True, "moving": False})
    assert r.phase == "alert" and r.alert["level"] == "stop"
    assert {"cmd": "alert", "level": "stop"} in transport.sent
    assert transport.cmds("stop"), "set stopped on the band"
    rec = r.session["exercises"][0]["sets"][0]
    assert rec["stopped_by_alert"] and rec["count"] == 1
    assert r.session["alerts"][-1]["exercise"] == "bicep_curl"

    with pytest.raises(SessionError):
        r.start_set()  # must clear first
    r.clear_alert()
    assert r.phase == "ready" and r.step.set == 2
    r.start_set()
    assert r.phase == "waiting_still"


def test_band_side_alert_is_respected(make_runner):
    r = make_runner(CURLS_THEN_PUSHUPS)
    r.start_session("T1")
    r.handle_band({"type": "alert", "level": "stop", "reason": "hr_above_max", "hr": 150, "hr_max": 140})
    assert r.phase == "alert"


def test_warning_does_not_stop(make_runner, transport):
    r = make_runner(CURLS_THEN_PUSHUPS)
    r.start_session("T1")
    lim = r.monitor.limits
    r.handle_band({"type": "vitals", "hr": lim.zone_high + 2, "hr_valid": True, "spo2_valid": False, "moving": False})
    assert r.alert["level"] == "warn" and r.phase == "waiting_still"
    r.handle_band({"type": "vitals", "hr": lim.zone_low + 2, "hr_valid": True, "spo2_valid": False, "moving": False})
    assert r.alert["level"] == "ok"
    assert {"cmd": "alert", "level": "none"} in transport.sent


def test_missing_set_done_falls_back_to_live_count(make_runner, clock):
    r = make_runner(CURLS_THEN_PUSHUPS)
    r.start_session("T1")
    r.handle_band({"type": "ready", "exercise": "bicep_curl", "set": 1})
    do_reps(r, "bicep_curl", 2)
    r.stop_set()
    clock.advance(SET_DONE_TIMEOUT_S + 0.5)
    r.tick()
    assert r.session["exercises"][0]["sets"][0]["count"] == 2
    assert r.phase == "resting"


def test_cv_count_is_kept_as_a_cross_check_for_wrist_exercises(make_runner):
    r = make_runner(CURLS_THEN_PUSHUPS)
    r.start_session("T1")
    r.handle_band({"type": "ready", "exercise": "bicep_curl", "set": 1})
    do_reps(r, "bicep_curl", 3)
    r.handle_cv({"exercise": "bicep_curl", "reps": 2, "form_score": 0.6})
    assert r.snapshot()["count"] == 3 and r.snapshot()["cv_count"] == 2
    r.handle_band({"type": "set_done", "exercise": "bicep_curl", "set": 1, "count": 3})
    s = r.session["exercises"][0]["sets"][0]
    assert s["count"] == 3 and s["cv_count"] == 2 and s["form_score"] == 0.6


def test_cv_without_session_or_unknown_exercise(make_runner):
    r = make_runner(CURLS_THEN_PUSHUPS)
    with pytest.raises(SessionError):
        r.handle_cv({"exercise": "dead_bug", "reps": 1})
    r.start_session("T1")
    with pytest.raises(SessionError):
        r.handle_cv({"exercise": "moonwalk", "reps": 1})


def test_hold_exercise_counts_seconds_from_status(make_runner):
    r = make_runner([{"exercise": "wall_sit", "sets": 1, "target": 20, "rest_s": 0}])
    r.start_session("T1")
    r.handle_band({"type": "ready", "exercise": "wall_sit", "set": 1})
    r.handle_band({"type": "status", "exercise": "wall_sit", "count": 12, "partial": 0, "state": "active"})
    assert r.snapshot()["count"] == 12


def test_timer_step_and_manual_mode(make_runner, transport, clock):
    r = make_runner([{"exercise": "warmup_march", "sets": 1, "target": 60, "rest_s": 0},
                     {"exercise": "bicep_curl", "sets": 1, "target": 3, "rest_s": 0}], auto_advance=False)
    r.start_session("T1")
    assert r.phase == "ready"
    r.start_set()
    clock.advance(61)
    r.tick()
    assert r.phase == "ready" and r.step.exercise == "bicep_curl", "manual mode waits for Start set"
    assert not transport.cmds("start")


def test_skip_and_manual_count_and_end(make_runner, transport, db):
    r = make_runner(CURLS_THEN_PUSHUPS)
    r.start_session("T1")
    r.skip()
    assert transport.cmds("stop")
    assert r.session["exercises"][0]["sets"][0]["skipped"] is True
    assert r.phase == "waiting_still" and r.step.set == 2, "skip moves on without resting"
    r.complete_manual(2)
    assert r.session["exercises"][0]["sets"][1]["count"] == 2
    r.end_session("ended_early")
    assert db.session(r.session["id"])["status"] == "ended_early"


def test_cannot_start_two_sessions(make_runner):
    r = make_runner(CURLS_THEN_PUSHUPS)
    r.start_session("T1")
    with pytest.raises(SessionError):
        r.start_session("T1")


def test_unknown_patient(make_runner):
    r = make_runner(CURLS_THEN_PUSHUPS)
    with pytest.raises(SessionError):
        r.start_session("nobody")


def test_stale_messages_are_ignored(make_runner):
    r = make_runner(CURLS_THEN_PUSHUPS)
    r.start_session("T1")
    r.handle_band({"type": "rep", "exercise": "shoulder_press", "rep": 1})
    r.handle_band({"type": "set_done", "exercise": "shoulder_press", "count": 9})
    assert r.snapshot()["count"] == 0 and r.session["exercises"] == []
