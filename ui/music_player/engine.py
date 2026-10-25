from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

from .ipc import EngineIPC

SERVICE_UNIT = "music-player-engine.service"


def service_unit(socket_path: str | Path, default_socket: str | Path, env: dict | None = None) -> str | None:
    """The systemd user unit to start the engine with, or None to spawn it directly.

    Only when the unit is installed, systemctl exists, the window uses the default
    socket (the unit does), and MUSIC_PLAYER_NO_SYSTEMD is not set.
    """
    env = os.environ if env is None else env
    if str(env.get("MUSIC_PLAYER_NO_SYSTEMD", "")).lower() in {"1", "true", "yes"}:
        return None
    if Path(socket_path) != Path(default_socket) or not shutil.which("systemctl"):
        return None
    config = Path(env.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    for base in (config / "systemd" / "user", Path("/etc/systemd/user"), Path("/usr/lib/systemd/user")):
        if (base / SERVICE_UNIT).is_file():
            return SERVICE_UNIT
    return None


def _systemctl(*args: str, timeout: float = 8.0) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None


class EngineSupervisor:
    def __init__(self, *, binary: str, socket_path: str, ipc: EngineIPC, service: str | None = None, systemctl=None):
        self.binary = binary
        self.socket_path = socket_path
        self.ipc = ipc
        self.service = service  # systemd user unit to try before spawning
        self._systemctl = systemctl or _systemctl
        self.proc: subprocess.Popen[bytes] | None = None
        self.owned = False
        self.via_service = False
        self._stderr_tail: list[bytes] = []

    def ensure(self, timeout: float = 20.0) -> bool:
        if self.ipc.alive():
            self.owned = False
            return True
        if self._existing_engine_pid():
            return self._wait_ready(timeout)
        if self.service and self._start_service(min(timeout, 12.0)):
            return True
        self._clear_stale()
        env = os.environ.copy()
        env["MUSIC_PLAYER_SOCK"] = str(self.socket_path)
        self._stderr_tail = []
        self.proc = subprocess.Popen(
            ["node", self.binary],
            cwd=str(Path(self.binary).resolve().parent.parent),
            env=env,
            start_new_session=True,
            stderr=subprocess.PIPE,
        )
        self.owned = True
        self._read_stderr()
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.ipc.alive():
                return False
            if self.proc.poll() is not None:
                time.sleep(0.05)
                detail = self.stderr_text() or "engine exited"
                raise RuntimeError(detail)
            time.sleep(0.1)
        detail = self.stderr_text()
        raise TimeoutError(detail or "engine did not become ready")

    def _start_service(self, timeout: float) -> bool:
        """Start the engine through systemd; False means fall back to spawning it."""
        started = self._systemctl("start", self.service)
        if started is None or started.returncode != 0:
            return False
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.ipc.alive():
                self.owned = False
                self.via_service = True
                return True
            state = self._systemctl("is-active", self.service, timeout=3.0)
            if state is not None and state.stdout.strip() in {"failed", "inactive"} and not self._existing_engine_pid():
                return False
            time.sleep(0.2)
        return False

    def _read_stderr(self) -> None:
        proc = self.proc
        if proc is None or getattr(proc, "stderr", None) is None:
            return

        def drain() -> None:
            try:
                while True:
                    chunk = proc.stderr.readline()
                    if not chunk:
                        break
                    self._stderr_tail.append(chunk)
                    if len(self._stderr_tail) > 40:
                        del self._stderr_tail[:-40]
            except OSError:
                pass

        threading.Thread(target=drain, daemon=True).start()

    def stderr_text(self) -> str:
        return b"".join(self._stderr_tail).decode(errors="replace").strip()

    def _existing_engine_pid(self) -> int:
        pid_path = Path(str(self.socket_path) + ".pid")
        if not pid_path.is_file():
            return 0
        try:
            pid = int(pid_path.read_text().strip())
        except ValueError:
            return 0
        if pid <= 0:
            return 0
        try:
            os.kill(pid, 0)
            return pid
        except OSError:
            return 0

    def _wait_ready(self, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.ipc.alive():
                self.owned = False
                return True
            if not self._existing_engine_pid():
                break
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
        self._kill_orphan_mpv()
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
                    if self.ipc.alive():
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

    def _kill_orphan_mpv(self) -> None:
        mpv_sock = str(Path(self.socket_path).with_name("mpv.sock"))
        try:
            proc = subprocess.run(
                ["pgrep", "-f", f"input-ipc-server={mpv_sock}"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return
        for raw in proc.stdout.split():
            try:
                os.kill(int(raw), signal.SIGTERM)
            except (ValueError, OSError):
                continue

    def _kill_pidfile(self) -> None:
        pid_path = Path(str(self.socket_path) + ".pid")
        if not pid_path.is_file():
            return
        try:
            pid = int(pid_path.read_text().strip())
            os.kill(pid, signal.SIGTERM)
        except (ValueError, OSError):
            return
