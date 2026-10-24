from __future__ import annotations

import json
import socket
import threading
from pathlib import Path
from typing import Any


class EngineError(RuntimeError):
    pass


# Status and the meter stay on their own socket so a slow search cannot stall them.
# Transport stays ordered on a second socket. Everything else shares a third.
FAST_CMDS = frozenset({"status", "bands"})
TRANSPORT_CMDS = frozenset(
    {
        "play",
        "pause",
        "toggle",
        "stop",
        "next",
        "prev",
        "seek",
        "volume",
        "shuffle",
        "repeat",
        "automix",
        "sleep",
        "eq",
        "queue.play",
        "queue.move",
        "queue.remove",
    }
)


def lane_for(cmd: str) -> str:
    name = (cmd or "").strip()
    if name in FAST_CMDS:
        return "fast"
    if name in TRANSPORT_CMDS:
        return "transport"
    return "query"


class _Lane:
    def __init__(self) -> None:
        self.sock: socket.socket | None = None
        self.buf = b""
        self.lock = threading.Lock()


class EngineIPC:
    def __init__(self, socket_path: str | Path, timeout: float = 30.0):
        self.socket_path = str(socket_path)
        self.timeout = timeout
        self._lanes = {name: _Lane() for name in ("fast", "transport", "query")}

    def alive(self) -> bool:
        try:
            resp = self.request({"cmd": "status"}, raise_on_error=False)
        except OSError:
            return False
        return bool(resp.get("ok"))

    def close(self) -> None:
        for lane in self._lanes.values():
            self._close_lane(lane)

    def request(self, payload: dict[str, Any], *, timeout: float | None = None, raise_on_error: bool = True) -> dict[str, Any]:
        deadline = self.timeout if timeout is None else timeout
        lane = self._lanes[lane_for(str(payload.get("cmd") or ""))]
        with lane.lock:
            resp = self._exchange(lane, payload, deadline)
        if raise_on_error and not resp.get("ok", True):
            raise EngineError(resp.get("error") or "engine error")
        return resp

    def _exchange(self, lane: _Lane, payload: dict[str, Any], deadline: float) -> dict[str, Any]:
        data = (json.dumps(payload) + "\n").encode()
        last: OSError | EngineError | None = None
        for attempt in range(2):
            try:
                sock = self._ensure(lane, deadline)
                sock.sendall(data)
                return self._read_json(lane, sock)
            except (OSError, EngineError) as exc:
                last = exc
                self._close_lane(lane)
                if attempt == 1:
                    raise
        raise last or EngineError("engine unreachable")

    def _ensure(self, lane: _Lane, deadline: float) -> socket.socket:
        if lane.sock is not None:
            lane.sock.settimeout(deadline)
            return lane.sock
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(deadline)
        sock.connect(self.socket_path)
        lane.sock = sock
        lane.buf = b""
        return sock

    def _close_lane(self, lane: _Lane) -> None:
        sock = lane.sock
        lane.sock = None
        lane.buf = b""
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _read_json(self, lane: _Lane, sock: socket.socket) -> dict[str, Any]:
        buf = lane.buf
        while b"\n" not in buf:
            chunk = sock.recv(65536)
            if not chunk:
                raise EngineError("empty engine response")
            buf += chunk
        line, rest = buf.split(b"\n", 1)
        lane.buf = rest
        if not line.strip():
            raise EngineError("empty engine response")
        return json.loads(line.decode())
