import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wristband.catalog import load_catalog  # noqa: E402
from wristband.database import Database  # noqa: E402
from wristband.session import SessionRunner  # noqa: E402
from wristband.transport import Transport  # noqa: E402


class FakeTransport(Transport):
    """Records what the app sends to the band; tests inject band messages by hand."""

    name = "fake"

    def __init__(self):
        super().__init__()
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)

    @property
    def connected(self):
        return True

    def cmds(self, name):
        return [m for m in self.sent if m.get("cmd") == name]


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


@pytest.fixture
def catalog():
    return load_catalog()


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "db.json")


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def transport():
    return FakeTransport()


@pytest.fixture
def make_runner(db, catalog, transport, clock):
    def make(prescription, auto_advance=True, **patient):
        db.upsert_patient({"id": "T1", "name": "Test", "age": 70, "resting_hr": 70, **patient,
                           "prescription": {"exercises": prescription}})
        return SessionRunner(db, catalog, transport, auto_advance=auto_advance, clock=clock)

    return make
