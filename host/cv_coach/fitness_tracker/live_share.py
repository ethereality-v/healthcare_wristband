"""Share the camera coach's live results with the Man-GO dashboard.

Runs a tiny web server on this computer only (127.0.0.1). The dashboard
(host/live_dashboard/index.html) asks it for the latest results a few times
per second at http://127.0.0.1:8765/cv. Uses only the Python standard library.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_PORT = 8765


class LiveShare:
    """Holds the latest tracker results and serves them as JSON."""

    def __init__(self, port: int = DEFAULT_PORT) -> None:
        self.port = port
        self._lock = threading.Lock()
        self._latest: dict = {"running": True, "exercise": None}
        self._server: ThreadingHTTPServer | None = None

    def start(self) -> bool:
        """Start serving in the background. Returns False if the port is busy."""
        share = self

        class Handler(BaseHTTPRequestHandler):
            def _headers(self, status: int = 200) -> None:
                self.send_response(status)
                # The dashboard is opened as a local file, so allow any page on
                # this computer to read the results.
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Private-Network", "true")
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.send_header("Cache-Control", "no-store")

            def do_OPTIONS(self) -> None:  # noqa: N802 (name required by http.server)
                self._headers(204)
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                if self.path.split("?")[0] not in ("/cv", "/"):
                    self._headers(404)
                    self.end_headers()
                    return
                body = json.dumps(share.snapshot()).encode("utf-8")
                self._headers(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args) -> None:
                # Keep the terminal quiet: the dashboard asks several times a second.
                pass

        try:
            self._server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        except OSError:
            self._server = None
            return False

        thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        thread.start()
        return True

    def publish(self, spec, tracker, view, paused: bool, fps: float) -> None:
        """Store the results for the current frame."""
        timed = hasattr(tracker, "active_seconds")
        data = {
            "running": True,
            "updated": time.time(),
            "exercise": spec.name,
            "key": spec.hotkey,
            "camera": spec.camera,
            "kind": "time" if timed else "reps",
            "count": int(getattr(tracker, "count", 0)),
            "left": int(getattr(tracker, "left_count", 0)),
            "right": int(getattr(tracker, "right_count", 0)),
            "seconds": round(float(tracker.active_seconds), 1) if timed else None,
            "value": view.value,
            "stage": view.stage,
            "metric": view.metric,
            "cue": view.cue,
            "detected": bool(view.detected),
            "paused": bool(paused),
            "fps": round(fps, 1),
        }
        with self._lock:
            self._latest = data

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._latest)

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
