from __future__ import annotations

import json
import socket
import threading
from pathlib import Path
from typing import Any


class EngineError(RuntimeError):
    pass


class EngineIPC:
    def __init__(self, socket_path: str | Path, timeout: float = 30.0):
        self.socket_path = str(socket_path)
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._buf = b""
        self._lock = threading.Lock()

    def alive(self) -> bool:
        try:
            resp = self.request({"cmd": "status"}, raise_on_error=False)
        except OSError:
            return False
        return bool(resp.get("ok"))

    def close(self) -> None:
        sock = self._sock
        self._sock = None
        self._buf = b""
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def request(self, payload: dict[str, Any], *, timeout: float | None = None, raise_on_error: bool = True) -> dict[str, Any]:
        deadline = self.timeout if timeout is None else timeout
        with self._lock:
            resp = self._exchange(payload, deadline)
        if raise_on_error and not resp.get("ok", True):
            raise EngineError(resp.get("error") or "engine error")
        return resp

    def _exchange(self, payload: dict[str, Any], deadline: float) -> dict[str, Any]:
        data = (json.dumps(payload) + "\n").encode()
        last: OSError | EngineError | None = None
        for attempt in range(2):
            try:
                sock = self._ensure(deadline)
                sock.sendall(data)
                return self._read_json(sock)
            except (OSError, EngineError) as exc:
                last = exc
                self.close()
                if attempt == 1:
                    raise
        raise last or EngineError("engine unreachable")

    def _ensure(self, deadline: float) -> socket.socket:
        if self._sock is not None:
            self._sock.settimeout(deadline)
            return self._sock
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(deadline)
        sock.connect(self.socket_path)
        self._sock = sock
        self._buf = b""
        return sock

    def _read_json(self, sock: socket.socket) -> dict[str, Any]:
        buf = self._buf
        while b"\n" not in buf:
            chunk = sock.recv(65536)
            if not chunk:
                raise EngineError("empty engine response")
            buf += chunk
        line, rest = buf.split(b"\n", 1)
        self._buf = rest
        if not line.strip():
            raise EngineError("empty engine response")
        return json.loads(line.decode())
