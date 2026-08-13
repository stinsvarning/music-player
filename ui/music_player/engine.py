from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

from .ipc import EngineIPC


class EngineSupervisor:
    def __init__(self, *, binary: str, socket_path: str, ipc: EngineIPC):
        self.binary = binary
        self.socket_path = socket_path
        self.ipc = ipc
        self.proc: subprocess.Popen[bytes] | None = None
        self.owned = False

    def ensure(self, timeout: float = 12.0) -> bool:
        if self.ipc.alive():
            self.owned = False
            return True
        self._clear_stale()
        env = os.environ.copy()
        self.proc = subprocess.Popen(
            ["node", self.binary],
            cwd=str(Path(self.binary).resolve().parent.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
        self.owned = True
        deadline = time.time() + timeout
        err = b""
        while time.time() < deadline:
            if self.ipc.alive():
                return False
            if self.proc.poll() is not None:
                if self.proc.stderr:
                    err = self.proc.stderr.read() or b""
                raise RuntimeError((err.decode(errors="replace") or "engine exited").strip())
            time.sleep(0.1)
        raise TimeoutError("engine did not become ready")

    def shutdown(self) -> None:
        try:
            self.ipc.request({"cmd": "shutdown"}, timeout=1.5, raise_on_error=False)
        except OSError:
            pass
        if self.owned and self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except OSError:
                try:
                    self.proc.terminate()
                except OSError:
                    pass
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except OSError:
                    pass
        self._kill_pidfile()
        self.owned = False
        self.proc = None

    def _clear_stale(self) -> None:
        sock = Path(self.socket_path)
        pid_path = Path(str(self.socket_path) + ".pid")
        if pid_path.is_file():
            try:
                pid = int(pid_path.read_text().strip())
            except ValueError:
                pid = 0
            if pid:
                try:
                    os.kill(pid, 0)
                    return
                except OSError:
                    pass
            try:
                pid_path.unlink()
            except OSError:
                pass
        if sock.exists():
            try:
                sock.unlink()
            except OSError:
                pass

    def _kill_pidfile(self) -> None:
        pid_path = Path(str(self.socket_path) + ".pid")
        if not pid_path.is_file():
            return
        try:
            pid = int(pid_path.read_text().strip())
            os.kill(pid, signal.SIGTERM)
        except (ValueError, OSError):
            return
