from __future__ import annotations

import os
import signal
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gio, GLib, GLibUnix, Gtk

from .engine import EngineSupervisor
from .ipc import EngineIPC
from .window import PlayerWindow


def default_socket() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "music-player" / "engine.sock"


def engine_entry() -> str:
    return str(Path(__file__).resolve().parents[2] / "engine" / "src" / "index.js")


class MusicApplication(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="stream.music.Player", flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.supervisor: EngineSupervisor | None = None
        self.window: PlayerWindow | None = None
        self._stopping = False

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self._signal_quit)
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self._signal_quit)

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return
        sock = default_socket()
        ipc = EngineIPC(sock)
        self.supervisor = EngineSupervisor(binary=engine_entry(), socket_path=str(sock), ipc=ipc)
        try:
            self.supervisor.ensure()
        except Exception as exc:  # noqa: BLE001
            self._fail(str(exc))
            return
        self.window = PlayerWindow(self, ipc)
        self.window.connect("close-request", self._on_close)
        self.window.present()

    def do_shutdown(self) -> None:
        self._stop()
        Gtk.Application.do_shutdown(self)

    def _on_close(self, *_a) -> bool:
        self._stop()
        return False

    def _signal_quit(self) -> bool:
        self._stop()
        self.quit()
        return GLib.SOURCE_REMOVE

    def _stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        if self.window is not None:
            self.window.stop_pump()
        if self.supervisor is not None:
            self.supervisor.shutdown()

    def _fail(self, message: str) -> None:
        dialog = Gtk.AlertDialog(message="music-player", detail=message)
        dialog.show(None)
        GLib.timeout_add(80, self.quit)
