from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any


class EngineError(RuntimeError):
    pass


class EngineIPC:
    def __init__(self, socket_path: str | Path, timeout: float = 30.0):
        self.socket_path = str(socket_path)
        self.timeout = timeout

    def alive(self) -> bool:
        try:
            resp = self.request({"cmd": "status"}, raise_on_error=False)
        except OSError:
            return False
        return bool(resp.get("ok"))

    def request(self, payload: dict[str, Any], *, timeout: float | None = None, raise_on_error: bool = True) -> dict[str, Any]:
        deadline = self.timeout if timeout is None else timeout
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(deadline)
        try:
            sock.connect(self.socket_path)
            sock.sendall((json.dumps(payload) + "\n").encode())
            buf = b""
            while b"\n" not in buf:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
        finally:
            sock.close()
        if not buf.strip():
            raise EngineError("empty engine response")
        resp = json.loads(buf.split(b"\n", 1)[0].decode())
        if raise_on_error and not resp.get("ok", True):
            raise EngineError(resp.get("error") or "engine error")
        return resp
