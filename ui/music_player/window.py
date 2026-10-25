"""The main player window. Behaviour lives in the mixins it is built from."""

from __future__ import annotations

import queue
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, GLib, Gtk

from .appearance import AppearanceMixin
from .controls import ControlsMixin
from .deck import DeckMixin
from .engine_link import EngineLinkMixin
from .footer import FooterMixin
from .ipc import EngineIPC
from .keys import KeysMixin
from .layout import DECK_H, DECK_W, bind_ellipsize, constrain_scroll
from .library import LibraryMixin
from .login import LoginMixin
from .models import BrowseState, PlaylistInfo, PlayerStatus, SeekGate, Track
from .prefs import load_vis_mode
from .queue_view import QueueViewMixin
from .theme import load_active_palette

WINDOW_W = 1180
WINDOW_H = 880

__all__ = ["DECK_H", "DECK_W", "PlayerWindow", "bind_ellipsize", "constrain_scroll"]


class PlayerWindow(
    DeckMixin,
    KeysMixin,
    AppearanceMixin,
    EngineLinkMixin,
    ControlsMixin,
    QueueViewMixin,
    FooterMixin,
    LoginMixin,
    LibraryMixin,
    Gtk.ApplicationWindow,
):
    def __init__(self, app: Gtk.Application, ipc: EngineIPC):
        super().__init__(application=app, title="Music")
        self.set_default_size(WINDOW_W, WINDOW_H)
        self.set_size_request(720, 540)
        self.maximize()
        self.add_css_class("app-window")
        self.ipc = ipc
        self.status = PlayerStatus()
        self._syncing = False
        self._seek = SeekGate()
        self._seek_timer = 0
        self._base_palette = load_active_palette()
        self._palette = self._base_palette
        self._css = Gtk.CssProvider()
        self._queue: list[Track] = []
        self._playlists: list[PlaylistInfo] = []
        self.browse = BrowseState()
        self._queue_sig = ""
        self._dragging = False
        self._drag_from: int | None = None
        self._ctx_pop: Gtk.Popover | None = None
        self._theme_monitors: list = []
        self._theme_reload_id = 0
        self._sleep_minutes = 30
        self._sleep_picking = False
        self._rating_syncing = False
        self._rating_track = ""
        self._rating_hold_until = 0.0
        self._cmd_lanes = {"transport": queue.Queue(), "query": queue.Queue()}
        self._pump_stop = threading.Event()
        self._login_timer = 0
        self._login_busy = False
        self._lyrics_id = ""
        self._lyrics_token = 0
        self._lyric_lines: list[str] = []
        self._playlists_token = 0
        self._notice = ""
        self._notice_until = 0.0
        self._footer_text = ""
        self._footer_kind = "idle"
        self._footer_timer = 0
        self._engine_seen = False
        # Status arrives pushed from the engine (subscribe); polling is only a fallback.
        self._subscribed = False
        self._playing_hint = False
        self._pos_base = (0.0, 0.0)  # (position, monotonic time it was true)
        self._pos_timer = 0

        self._install_icons()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            self._css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        self._mapped = False
        self._login_spec = ""
        self._build()
        self._apply_vis(load_vis_mode())
        self._apply_palette(self._palette)
        self._watch_theme()
        self._bind_keys()
        self.connect("map", self._on_map)

    def _on_map(self, *_a) -> None:
        if self._mapped:
            return
        self._mapped = True
        threading.Thread(target=self._pump, name="music-status", daemon=True).start()
        threading.Thread(target=self._subscribe_loop, name="music-events", daemon=True).start()
        threading.Thread(target=self._command_loop, args=("transport",), name="music-transport", daemon=True).start()
        threading.Thread(target=self._command_loop, args=("query",), name="music-query", daemon=True).start()
        GLib.idle_add(self._bootstrap)

    def stop_pump(self) -> None:
        self._pump_stop.set()
        self._stop_login_watch()
        if self._seek_timer:
            GLib.source_remove(self._seek_timer)
            self._seek_timer = 0
        if self._footer_timer:
            GLib.source_remove(self._footer_timer)
            self._footer_timer = 0
        if self._pos_timer:
            GLib.source_remove(self._pos_timer)
            self._pos_timer = 0
