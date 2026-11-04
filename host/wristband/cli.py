"""Command line entry point:  python -m wristband <command>

  run      start the dashboard + band link   (--port COM3 | --udp | --simulate)
  ports    list serial ports (find your ESP32)
  monitor  print what the band sends; --raw-csv saves raw accelerometer data for tuning
  report   print a patient's session history
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
import webbrowser
from pathlib import Path

from .catalog import REPO_ROOT
from .database import Database
from .transport import SerialTransport, SimulatedTransport, UdpTransport, list_serial_ports

DEFAULT_DB = REPO_ROOT / "data" / "database.json"
EXAMPLE_PATIENT = REPO_ROOT / "data" / "example_patient.json"


def _transport(args):
    if args.simulate:
        return SimulatedTransport(speed=args.speed)
    if args.udp:
        return UdpTransport(listen_port=args.udp_port)
    if args.port:
        return SerialTransport(args.port, args.baud)
    ports = list_serial_ports()
    if len(ports) == 1:
        print(f"Using the only serial port found: {ports[0]['port']}")
        return SerialTransport(ports[0]["port"], args.baud)
    print("Choose how to reach the band: --port COM3 (USB), --udp (Wi-Fi) or --simulate (no hardware).")
    if ports:
        print("Serial ports found: " + ", ".join(p["port"] for p in ports))
    sys.exit(2)


def seed_example_patient(db: Database) -> None:
    if db.patients() or not EXAMPLE_PATIENT.exists():
        return
    db.upsert_patient(json.loads(EXAMPLE_PATIENT.read_text(encoding="utf-8")))
    print(f"Added example patient from {EXAMPLE_PATIENT.relative_to(REPO_ROOT)}")


def cmd_run(args) -> int:
    from .server import build, serve, start_ticker

    transport = _transport(args)
    app = build(args.db, transport, auto_advance=not args.manual)
    seed_example_patient(app.db)
    httpd = serve(app, args.host, args.http_port)
    stop = threading.Event()
    start_ticker(app.runner, stop)

    url = f"http://{'localhost' if args.host in ('0.0.0.0', '127.0.0.1') else args.host}:{args.http_port}"
    print(f"Band link : {transport.describe()}")
    print(f"Database  : {args.db}")
    print(f"Dashboard : {url}   (CV coach posts to {url}/api/cv)")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        stop.set()
        try:
            if app.runner.session and app.runner.phase not in ("finished", "idle"):
                app.runner.end_session("interrupted")
        finally:
            httpd.shutdown()
            transport.close()
    return 0


def cmd_ports(args) -> int:
    ports = list_serial_ports()
    if not ports:
        print("No serial ports found. Is the ESP32 plugged in (and the USB driver installed)?")
    for p in ports:
        print(f"{p['port']:12} {p['description']}")
    return 0


def cmd_monitor(args) -> int:
    transport = _transport(args)
    csv = open(args.raw_csv, "w", encoding="utf-8") if args.raw_csv else None
    if csv:
        csv.write("t_ms,ax,ay,az\n")

    def show(msg: dict) -> None:
        if msg.get("type") == "raw":
            if csv:
                csv.write(f"{msg['t']},{msg['ax']},{msg['ay']},{msg['az']}\n")
            return
        if msg.get("type") == "status" and not args.status:
            return
        print(json.dumps(msg))

    transport.start(show)
    time.sleep(2.5)  # the ESP32 resets when the port opens
    transport.send({"cmd": "ping"})
    if csv:
        transport.send({"cmd": "raw", "on": True})
        print(f"Recording raw accelerometer data to {args.raw_csv}")
    if args.exercise:
        transport.send({"cmd": "start", "exercise": args.exercise, "target": args.target})
    print("Type a JSON command and press Enter (e.g. {\"cmd\":\"stop\"}); Ctrl+C to quit.")
    try:
        for line in sys.stdin:
            line = line.strip()
            if line:
                try:
                    transport.send(json.loads(line))
                except json.JSONDecodeError:
                    print("not JSON")
    except KeyboardInterrupt:
        pass
    finally:
        if csv:
            transport.send({"cmd": "raw", "on": False})
            csv.close()
        transport.close()
    return 0


def cmd_report(args) -> int:
    db = Database(args.db)
    rows = db.session_summaries(args.patient)
    if not rows:
        print("No sessions yet.")
        return 0
    print(f"{'session':22} {'status':11} {'done':>5} {'avgHR':>6} {'maxHR':>6} {'stops':>5} {'RPE':>4}")
    for r in rows:
        done = f"{r['completion']:.0%}" if r["completion"] is not None else "-"
        print(f"{r['id']:22} {r['status']:11} {done:>5} {str(r['avg_hr'] or '-'):>6} {str(r['max_hr'] or '-'):>6} "
              f"{r['stops']:>5} {str(r['rpe'] or '-'):>4}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m wristband", description="Healthcare wristband laptop app")
    sub = parser.add_subparsers(dest="command", required=True)

    def link_options(p):
        p.add_argument("--port", help="serial port of the ESP32, e.g. COM3 or /dev/ttyUSB0")
        p.add_argument("--baud", type=int, default=115200)
        p.add_argument("--udp", action="store_true", help="receive the band over Wi-Fi (UDP)")
        p.add_argument("--udp-port", type=int, default=5005)
        p.add_argument("--simulate", action="store_true", help="use the built-in simulated band")
        p.add_argument("--speed", type=float, default=1.0, help="simulator speed multiplier")

    p_run = sub.add_parser("run", help="start the dashboard and connect to the band")
    link_options(p_run)
    p_run.add_argument("--db", default=str(DEFAULT_DB))
    p_run.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 so the CV coach can post from another computer")
    p_run.add_argument("--http-port", type=int, default=8000)
    p_run.add_argument("--manual", action="store_true", help="don't start sets automatically after rest")
    p_run.add_argument("--no-browser", action="store_true")
    p_run.add_argument("-v", "--verbose", action="store_true")
    p_run.set_defaults(func=cmd_run)

    p_ports = sub.add_parser("ports", help="list serial ports")
    p_ports.set_defaults(func=cmd_ports)

    p_mon = sub.add_parser("monitor", help="print band messages / record raw data")
    link_options(p_mon)
    p_mon.add_argument("--status", action="store_true", help="also print the twice-a-second status messages")
    p_mon.add_argument("--raw-csv", help="save raw accelerometer samples to this CSV file")
    p_mon.add_argument("--exercise", help="start a set of this exercise right away")
    p_mon.add_argument("--target", type=int, default=10)
    p_mon.set_defaults(func=cmd_monitor)

    p_rep = sub.add_parser("report", help="print session history")
    p_rep.add_argument("--db", default=str(DEFAULT_DB))
    p_rep.add_argument("--patient")
    p_rep.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if getattr(args, "verbose", False) else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    Path(getattr(args, "db", DEFAULT_DB)).parent.mkdir(parents=True, exist_ok=True)
    return args.func(args)
