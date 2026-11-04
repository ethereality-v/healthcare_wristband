"""Dashboard and REST API (Python standard library only). Full endpoint list: docs/protocol.md."""

from __future__ import annotations

import json
import logging
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from . import dosage
from .catalog import Catalog
from .database import Database
from .prescription import Prescription
from .safety import limits_for
from .session import SessionError, SessionRunner

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class App:
    """Route table + handlers, kept separate from the HTTP plumbing so tests can call it directly."""

    def __init__(self, runner: SessionRunner, db: Database, catalog: Catalog):
        self.runner, self.db, self.catalog = runner, db, catalog
        self.routes = [
            ("GET", r"/api/state", self.get_state),
            ("GET", r"/api/catalog", lambda q, b: self.catalog.to_json()),
            ("GET", r"/api/patients", lambda q, b: self.db.patients()),
            ("POST", r"/api/patients", self.post_patient),
            ("GET", r"/api/patients/(?P<pid>[\w.-]+)", self.get_patient),
            ("POST", r"/api/patients/(?P<pid>[\w.-]+)/prescription", self.post_prescription),
            ("GET", r"/api/sessions", lambda q, b: self.db.session_summaries(q.get("patient"))),
            ("GET", r"/api/sessions/(?P<sid>[\w.-]+)", self.get_session),
            ("POST", r"/api/session/start", self.post_session_start),
            ("POST", r"/api/session/end", lambda q, b: self.runner.end_session(b.get("status", "completed"))),
            ("POST", r"/api/set/start", lambda q, b: self._ok(self.runner.start_set)),
            ("POST", r"/api/set/stop", lambda q, b: self._ok(self.runner.stop_set)),
            ("POST", r"/api/set/skip", lambda q, b: self._ok(self.runner.skip)),
            ("POST", r"/api/set/complete", lambda q, b: self._ok(self.runner.complete_manual, int(b.get("count", 0)))),
            ("POST", r"/api/alert/clear", lambda q, b: self._ok(self.runner.clear_alert)),
            ("POST", r"/api/rpe", lambda q, b: self._ok(self.runner.set_rpe, int(b.get("rpe", 0)))),
            ("POST", r"/api/cv", lambda q, b: self.runner.handle_cv(b)),
            ("POST", r"/api/band/calibrate", lambda q, b: self._band({"cmd": "calibrate"})),
            ("POST", r"/api/band/ping", lambda q, b: self._band({"cmd": "ping"})),
        ]

    def _ok(self, fn: Callable, *args) -> dict:
        fn(*args)
        return self.runner.snapshot()

    def _band(self, cmd: dict) -> dict:
        self.runner.transport.send(cmd)
        return {"sent": cmd}

    def dispatch(self, method: str, path: str, query: Dict[str, str], body: dict) -> Tuple[int, object]:
        for m, pattern, handler in self.routes:
            if m != method:
                continue
            match = re.fullmatch(pattern, path)
            if match:
                try:
                    return 200, handler({**query, **match.groupdict()}, body)
                except ApiError as e:
                    return e.status, {"error": str(e)}
                except SessionError as e:
                    return 409, {"error": str(e)}
                except (ValueError, TypeError, KeyError) as e:
                    return 400, {"error": str(e)}
        return 404, {"error": f"no route for {method} {path}"}

    # ---------- handlers ----------

    def get_state(self, q: dict, body: dict) -> dict:
        return self.runner.snapshot()

    def get_patient(self, q: dict, body: dict) -> dict:
        p = self.db.patient(q["pid"])
        if p is None:
            raise ApiError(404, "unknown patient")
        p["limits"] = limits_for(p).to_dict()
        p["warnings"] = Prescription.from_dict(p.get("prescription", {})).validate(self.catalog) if p.get("prescription") else []
        return p

    def post_patient(self, q: dict, body: dict) -> dict:
        allowed = {"id", "name", "age", "resting_hr", "beta_blocker", "hr_max", "hr_stop", "notes", "spo2_warn",
                   "spo2_stop", "prescription"}
        patient = {k: v for k, v in body.items() if k in allowed}
        if "prescription" in patient:
            Prescription.from_dict(patient["prescription"]).validate(self.catalog)
        return self.db.upsert_patient(patient)

    def post_prescription(self, q: dict, body: dict) -> dict:
        pid = q["pid"]
        patient = self.db.patient(pid)
        if patient is None:
            raise ApiError(404, "unknown patient")
        if "accept" in body:
            # clinician accepts dosage suggestions from a session
            session = self.db.session(body.get("session_id", "")) or {}
            current = Prescription.from_dict(patient["prescription"])
            new = dosage.apply(current, session.get("suggestions", []), body["accept"])
            note = f"accepted suggestions from session {session.get('id')}: {', '.join(body['accept'])}"
        else:
            new = Prescription.from_dict(body)
            note = body.get("note", "edited")
        warnings = new.validate(self.catalog)
        updated = self.db.set_prescription(pid, new, note)
        return {"patient": updated, "warnings": warnings}

    def get_session(self, q: dict, body: dict) -> dict:
        s = self.db.session(q["sid"])
        if s is None:
            raise ApiError(404, "unknown session")
        return s

    def post_session_start(self, q: dict, body: dict) -> dict:
        pid = body.get("patient_id")
        if not pid:
            raise ApiError(400, "patient_id is required")
        return self.runner.start_session(pid)


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "WristbandHTTP/1.0"

        def log_message(self, fmt, *args):  # keep the console quiet
            log.debug("%s %s", self.address_string(), fmt % args)

        def _cors(self):
            # the CV coach may run in a browser on another port
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def _send_json(self, status: int, payload) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(data)

        def _serve_static(self, name: str) -> None:
            path = (STATIC_DIR / name).resolve()
            if STATIC_DIR not in path.parents or not path.is_file():
                self._send_json(404, {"error": "not found"})
                return
            data = path.read_bytes()
            ctype = {"html": "text/html", "js": "text/javascript", "css": "text/css"}.get(path.suffix[1:], "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _handle(self, method: str) -> None:
            url = urlparse(self.path)
            if method == "GET" and not url.path.startswith("/api/"):
                self._serve_static("index.html" if url.path in ("/", "") else url.path.lstrip("/"))
                return
            body: dict = {}
            if method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    try:
                        body = json.loads(self.rfile.read(length) or b"{}")
                    except json.JSONDecodeError:
                        self._send_json(400, {"error": "body must be JSON"})
                        return
                    if not isinstance(body, dict):
                        self._send_json(400, {"error": "body must be a JSON object"})
                        return
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            status, payload = app.dispatch(method, url.path.rstrip("/") or "/", query, body)
            self._send_json(status, payload)

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

    return Handler


def serve(app: App, host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    threading.Thread(target=httpd.serve_forever, name="http", daemon=True).start()
    return httpd


def start_ticker(runner: SessionRunner, stop: threading.Event, interval: float = 0.2) -> threading.Thread:
    def loop():
        while not stop.wait(interval):
            try:
                runner.tick()
            except Exception:
                log.exception("tick failed")

    t = threading.Thread(target=loop, name="ticker", daemon=True)
    t.start()
    return t


def build(db_path: str, transport, auto_advance: bool = True, catalog: Optional[Catalog] = None):
    """Wires database, runner and app together (used by the CLI and the tests)."""
    from .catalog import load_catalog

    catalog = catalog or load_catalog()
    db = Database(db_path)
    runner = SessionRunner(db, catalog, transport, auto_advance=auto_advance)
    transport.start(runner.handle_band)
    return App(runner, db, catalog)
