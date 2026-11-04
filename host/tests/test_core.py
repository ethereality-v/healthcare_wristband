"""Catalog, prescriptions, safety, dosage and database."""

import json
import subprocess
import sys

import pytest

from wristband import dosage
from wristband.catalog import REPO_ROOT, SESSION_ORDER
from wristband.prescription import PrescribedExercise, Prescription, build_plan, default_prescription
from wristband.safety import STOP, WARN, OK, VitalsMonitor, limits_for, predicted_hr_max


# ---------- catalog ----------

def test_catalog_has_every_category(catalog):
    for cat in SESSION_ORDER:
        assert cat in catalog.categories
        assert catalog.in_category(cat), f"no exercises in {cat}"


def test_wrist_exercises_have_detection_settings(catalog):
    for ex in catalog.exercises.values():
        if ex.is_wrist:
            assert ex.mode in ("tilt", "motion", "hold"), ex.id


def test_firmware_table_matches_json():
    """The firmware's exercise table must be regenerated whenever shared/exercises.json changes."""
    result = subprocess.run([sys.executable, str(REPO_ROOT / "tools" / "gen_exercise_table.py"), "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_firmware_table_lists_exactly_the_wrist_exercises(catalog):
    table = (REPO_ROOT / "firmware" / "wristband" / "exercise_table.cpp").read_text()
    for ex in catalog.exercises.values():
        assert (f'{{"{ex.id}",' in table) == ex.is_wrist, ex.id


# ---------- prescriptions ----------

def test_default_prescription_follows_guidelines(catalog):
    rx = default_prescription()
    assert rx.validate(catalog) == []


def test_plan_is_in_session_order_and_expands_sets(catalog):
    rx = Prescription([
        PrescribedExercise("bicep_curl", sets=2, target=12, rest_s=60),
        PrescribedExercise("warmup_march", sets=1, target=300, rest_s=0),
        PrescribedExercise("arm_rainbow", sets=1, target=10, rest_s=30),
    ])
    plan = build_plan(rx, catalog)
    assert [s.exercise for s in plan] == ["warmup_march", "arm_rainbow", "bicep_curl", "bicep_curl"]
    assert [s.set for s in plan[2:]] == [1, 2]
    assert plan[2].rest_s == 60 and plan[3].rest_s == 60  # rest also before the next exercise
    assert [s.index for s in plan] == [0, 1, 2, 3]


def test_validation_errors_and_warnings(catalog):
    with pytest.raises(ValueError):
        Prescription([PrescribedExercise("moonwalk")]).validate(catalog)
    with pytest.raises(ValueError):
        Prescription([]).validate(catalog)
    warnings = Prescription([PrescribedExercise("bicep_curl", sets=3, target=30)]).validate(catalog)
    text = " ".join(warnings)
    assert "10-20" in text and "1-2" in text and "mobility" in text


def test_prescription_roundtrip():
    rx = default_prescription()
    assert Prescription.from_dict(json.loads(json.dumps(rx.to_dict()))).to_dict() == rx.to_dict()


# ---------- safety ----------

def test_limits_from_age_and_resting_hr():
    lim = limits_for({"age": 70, "resting_hr": 70})
    hr_max = predicted_hr_max(70)  # 159
    assert round(hr_max) == 159
    assert lim.zone_low == round(70 + 0.4 * (hr_max - 70))
    assert lim.zone_low < lim.zone_high < lim.hr_stop <= 180


def test_clinician_override():
    lim = limits_for({"age": 70, "resting_hr": 70, "hr_max": 130, "hr_stop": 120})
    assert lim.hr_stop == 120 and lim.zone_high < 120


def vit(hr=None, spo2=None, moving=False):
    return {"hr": hr or 0, "spo2": spo2 or 0, "hr_valid": hr is not None, "spo2_valid": spo2 is not None, "moving": moving}


def test_monitor_levels():
    lim = limits_for({"age": 70, "resting_hr": 70})
    m = VitalsMonitor(lim)
    assert m.add(vit(hr=lim.zone_low + 5, spo2=97)).level == OK
    assert m.add(vit(hr=lim.zone_high + 1, spo2=97)).level == WARN
    assert m.add(vit(hr=lim.hr_stop + 1, spo2=97)).level == STOP
    m2 = VitalsMonitor(lim)
    assert m2.add(vit(hr=90, spo2=92)).level == WARN
    assert m2.add(vit(hr=90, spo2=88)).level == STOP


def test_single_moving_reading_only_warns_but_two_in_a_row_stop():
    lim = limits_for({"age": 70, "resting_hr": 70})
    m = VitalsMonitor(lim)
    assert m.add(vit(hr=lim.hr_stop + 10, moving=True)).level == WARN
    assert m.add(vit(hr=lim.hr_stop + 10, moving=True)).level == STOP


def test_invalid_readings_are_ignored():
    m = VitalsMonitor(limits_for({"age": 70}))
    assert m.add({"hr": 250, "hr_valid": False, "spo2": 50, "spo2_valid": False}).level == OK


def test_beta_blocker_disables_zone_warning_but_keeps_stop():
    lim = limits_for({"age": 70, "resting_hr": 70, "beta_blocker": True})
    m = VitalsMonitor(lim)
    assert m.add(vit(hr=lim.zone_high + 5)).level == OK
    assert m.add(vit(hr=lim.hr_stop + 5)).level == STOP


# ---------- dosage ----------

def session_with(sets, rpe=None, alerts=(), vitals=()):
    return {"rpe": rpe, "alerts": list(alerts),
            "exercises": [{"exercise": "bicep_curl", "tracker": "wrist", "unit": "reps", "sets": sets, "vitals": list(vitals)}]}


RX = Prescription([PrescribedExercise("bicep_curl", sets=1, target=12)])


def test_progress_when_everything_done():
    s = dosage.suggest(session_with([{"target": 12, "count": 12}], rpe=12), RX, {"zone_high": 120})[0]
    assert s["action"] == "progress" and s["suggested"] == {"sets": 1, "target": 14}
    assert s["requires_clinician_approval"] is True


def test_progress_adds_a_set_at_20_reps():
    rx = Prescription([PrescribedExercise("bicep_curl", sets=1, target=20)])
    s = dosage.suggest(session_with([{"target": 20, "count": 20}]), rx)[0]
    assert s["suggested"] == {"sets": 2, "target": 10}


def test_regress_on_low_completion_and_on_safety_stop():
    s = dosage.suggest(session_with([{"target": 12, "count": 6}]), RX)[0]
    assert s["action"] == "regress" and s["suggested"]["target"] == 10
    s = dosage.suggest(session_with([{"target": 12, "count": 12}],
                                    alerts=[{"level": "stop", "exercise": "bicep_curl"}]), RX)[0]
    assert s["action"] == "regress"


def test_keep_when_hard_or_hr_high():
    assert dosage.suggest(session_with([{"target": 12, "count": 12}], rpe=16), RX)[0]["action"] == "keep"
    s = dosage.suggest(session_with([{"target": 12, "count": 12}], vitals=[{"hr": 140, "hr_valid": True}]), RX,
                       {"zone_high": 120})[0]
    assert s["action"] == "keep" and "above the zone" in " ".join(s["reasons"])


def test_apply_only_accepted():
    rx = Prescription([PrescribedExercise("bicep_curl", 1, 12), PrescribedExercise("front_raise", 1, 12)])
    sugg = [{"exercise": "bicep_curl", "suggested": {"sets": 1, "target": 14}},
            {"exercise": "front_raise", "suggested": {"sets": 1, "target": 10}}]
    new = dosage.apply(rx, sugg, ["bicep_curl"])
    assert [(e.exercise, e.target) for e in new.exercises] == [("bicep_curl", 14), ("front_raise", 12)]
    assert rx.exercises[0].target == 12  # original untouched


# ---------- database ----------

def test_database_roundtrip(tmp_path):
    from wristband.database import Database

    path = tmp_path / "sub" / "db.json"
    db = Database(path)
    db.upsert_patient({"id": "P9", "name": "A", "age": 60})
    s = db.new_session("P9", "test", [])
    s["exercises"].append({"exercise": "bicep_curl", "sets": [{"target": 10, "count": 8}]})
    s["vitals"].append({"hr": 100, "hr_valid": True})
    db.update_session(s)

    again = Database(path)
    assert again.patient("P9")["prescription"]["exercises"], "default prescription added"
    summary = again.session_summaries("P9")[0]
    assert summary["completion"] == 0.8 and summary["avg_hr"] == 100
    assert not list(path.parent.glob(".db-*")), "temporary files cleaned up"


def test_prescription_history_kept(db):
    db.upsert_patient({"id": "P1"})
    db.set_prescription("P1", Prescription([PrescribedExercise("bicep_curl", 1, 14)]), "progressed")
    p = db.patient("P1")
    assert p["prescription"]["exercises"][0]["target"] == 14
    assert p["prescription_history"][0]["note"] == "progressed"
