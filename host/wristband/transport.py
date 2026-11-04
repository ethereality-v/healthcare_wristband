"""Links between the laptop and the band. All of them speak newline-delimited JSON (docs/protocol.md).

- SerialTransport : USB cable (default)
- UdpTransport    : Wi-Fi; the band sends UDP to this laptop, commands go back to the band's address
- SimulatedTransport : no hardware needed (see simulator.py)
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
from typing import Callable, Optional

log = logging.getLogger(__name__)

MessageHandler = Callable[[dict], None]


def parse_line(line: str) -> Optional[dict]:
    """Band output line -> dict. Non-JSON lines (boot messages etc.) become {"type": "text"}."""
    line = line.strip()
    if not line:
        return None
    if line.startswith("{"):
        try:
            msg = json.loads(line)
            if isinstance(msg, dict):
                return msg
        except json.JSONDecodeError:
            pass
    return {"type": "text", "text": line}


class Transport:
    name = "base"

    def __init__(self) -> None:
        self._handler: Optional[MessageHandler] = None
        self.last_rx: float = 0.0

    def start(self, handler: MessageHandler) -> None:
        self._handler = handler

    def send(self, msg: dict) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass

    @property
    def connected(self) -> bool:
        return time.monotonic() - self.last_rx < 5.0

    def describe(self) -> str:
        return self.name

    def _deliver(self, msg: Optional[dict]) -> None:
        if msg is None:
            return
        self.last_rx = time.monotonic()
        if self._handler:
            try:
                self._handler(msg)
            except Exception:  # never let a bad message kill the reader thread
                log.exception("error handling band message %r", msg)


class SerialTransport(Transport):
    name = "serial"

    def __init__(self, port: str, baud: int = 115200):
        super().__init__()
        self.port, self.baud = port, baud
        self._serial = None
        self._stop = threading.Event()
        self._write_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def describe(self) -> str:
        return f"serial {self.port}"

    def start(self, handler: MessageHandler) -> None:
        super().start(handler)
        self._thread = threading.Thread(target=self._run, name="serial-reader", daemon=True)
        self._thread.start()

    def _open(self):
        import serial  # pyserial

        return serial.Serial(self.port, self.baud, timeout=0.5)

    def _run(self) -> None:
        buf = b""
        while not self._stop.is_set():
            if self._serial is None:
                try:
                    self._serial = self._open()
                    log.info("opened %s", self.port)
                except Exception as e:
                    log.warning("cannot open %s (%s); retrying", self.port, e)
                    self._stop.wait(2.0)
                    continue
            try:
                chunk = self._serial.read(512)
            except Exception as e:
                log.warning("serial read failed (%s); reconnecting", e)
                self._close_port()
                continue
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                self._deliver(parse_line(line.decode("utf-8", errors="replace")))

    def send(self, msg: dict) -> None:
        data = (json.dumps(msg, separators=(",", ":")) + "\n").encode()
        with self._write_lock:
            if self._serial is None:
                log.warning("band not connected; dropped %s", msg)
                return
            try:
                self._serial.write(data)
            except Exception as e:
                log.warning("serial write failed: %s", e)
                self._close_port()

    def _close_port(self) -> None:
        try:
            if self._serial:
                self._serial.close()
        except Exception:
            pass
        self._serial = None

    def close(self) -> None:
        self._stop.set()
        self._close_port()


class UdpTransport(Transport):
    name = "udp"

    def __init__(self, listen_port: int = 5005, band_port: int = 5006, band_ip: Optional[str] = None):
        super().__init__()
        self.listen_port, self.band_port = listen_port, band_port
        self.band_ip = band_ip  # learned from the first packet if not given
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("0.0.0.0", listen_port))
        self._sock.settimeout(0.5)
        self._stop = threading.Event()

    def describe(self) -> str:
        return f"wifi udp :{self.listen_port}" + (f" (band {self.band_ip})" if self.band_ip else "")

    def start(self, handler: MessageHandler) -> None:
        super().start(handler)
        threading.Thread(target=self._run, name="udp-reader", daemon=True).start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            if self.band_ip != addr[0]:
                log.info("band at %s", addr[0])
                self.band_ip = addr[0]
            for line in data.decode("utf-8", errors="replace").splitlines():
                self._deliver(parse_line(line))

    def send(self, msg: dict) -> None:
        if not self.band_ip:
            log.warning("band address unknown yet; dropped %s", msg)
            return
        self._sock.sendto((json.dumps(msg, separators=(",", ":")) + "\n").encode(), (self.band_ip, self.band_port))

    def close(self) -> None:
        self._stop.set()
        self._sock.close()


class SimulatedTransport(Transport):
    name = "simulator"

    def __init__(self, speed: float = 1.0, seed: Optional[int] = None, **band_options):
        super().__init__()
        from .simulator import SimulatedBand

        self.band = SimulatedBand(self._deliver, speed=speed, seed=seed, **band_options)

    def describe(self) -> str:
        return f"simulator (x{self.band.speed:g} speed)"

    def start(self, handler: MessageHandler) -> None:
        super().start(handler)
        self.band.start()

    def send(self, msg: dict) -> None:
        self.band.command(msg)

    def close(self) -> None:
        self.band.stop()


def list_serial_ports() -> list:
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [{"port": p.device, "description": p.description} for p in list_ports.comports()]
