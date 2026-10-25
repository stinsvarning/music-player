from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, Gio, GLib, GObject, Gtk

from .ipc import EngineError, EngineIPC, lane_for
from .layout import (
    DECK_FRAME,
    DECK_H,
    DECK_MARGIN,
    DECK_W,
    bind_ellipsize,
    caption_bar,
    clear_list,
    constrain_scroll,
    fit_deck,
    make_row,
)
from .prefs import config_path, load_vis_mode, save_vis_mode
from .spectrum import cycle_vis
from .library import LibraryMixin
from .login import LoginMixin
from .models import (
    BrowseState,
    PlaylistInfo,
    PlayerStatus,
    SeekGate,
    Track,
    default_queue_playlist_name,
    format_time,
    interpolate_position,
    footer_kind,
    is_login_error,
    lyric_lines,
    parse_status,
    playback_word,
    pump_intervals,
    parse_tracks,
    queue_needs_rebuild,
    should_apply_engine_rating,
    song_menu_actions,
)
from .theme import (
    Palette,
    css_for,
    load_active_palette,
    omarchy_colors_paths,
    omarchy_current_dir,
    omarchy_state_dir,
)
from .widgets.field import FieldView
from .widgets.spectrum import SpectrumView

HELP_LINES = (
    "space      play / pause",
    "n  p  s    next, previous, stop",
    "left right seek",
    "up down    volume",
    "l          like",
    "q  m       queue, library",
    "/          find",
    "delete     remove the selected queue row",
    "menu       open the context menu",
    "f11        fullscreen",
    "ctrl+q     quit",
    "?          close this card",
)
WINDOW_W = 1180
WINDOW_H = 880
_ICON_MARK = {
    "media-skip-backward-symbolic": ("go-previous-symbolic", "PREV"),
    "media-skip-forward-symbolic": ("go-next-symbolic", "NEXT"),
    "media-playlist-shuffle-symbolic": ("", "SHUF"),
    "media-playlist-consecutive-symbolic": ("", "MIX"),
    "alarm-symbolic": ("", "SLEEP"),
}

__all__ = ["PlayerWindow", "bind_ellipsize", "constrain_scroll"]


class PlayerWindow(LoginMixin, LibraryMixin, Gtk.ApplicationWindow):
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

    def _build(self) -> None:
        self._install_header()
        self.field = FieldView()
        stage = Gtk.Overlay()
        stage.add_css_class("stage")
        stage.set_child(self.field)
        deck = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        deck.add_css_class("deck")
        deck.set_size_request(DECK_W + DECK_FRAME, DECK_H + DECK_FRAME)
        deck.set_hexpand(False)
        deck.set_vexpand(False)
        deck.set_halign(Gtk.Align.CENTER)
        deck.set_valign(Gtk.Align.CENTER)
        deck.set_overflow(Gtk.Overflow.HIDDEN)
        deck.append(self._deck_bar())
        deck.append(self._lcd())
        deck.append(self._transport())
        self.body_box = self._body()
        deck.append(self.body_box)
        deck.append(self._footer())
        self.deck = deck
        self.deck_fit = fit_deck(DECK_W + DECK_FRAME + 2 * DECK_MARGIN, DECK_H + DECK_FRAME + 2 * DECK_MARGIN)
        self._deck_mode = (False, False)  # (compact, narrow) currently applied
        self._deck_mode_pending = False
        self.field.set_deck(deck)
        stage.add_overlay(deck)
        self.field.connect("resize", self._on_stage_resize)
        stage.add_overlay(self._login_overlay())
        stage.add_overlay(self._help_overlay())
        self.set_child(stage)

    def _on_stage_resize(self, _field, width: int, height: int) -> None:
        """Size the deck to the window: the design size when it fits, smaller in tiles."""
        fit = fit_deck(width, height)
        if fit == self.deck_fit and not self._deck_mode_pending:
            return
        self.deck_fit = fit
        if not self._deck_mode_pending:
            # Resizing and restyling the deck mid-allocation is not allowed.
            self._deck_mode_pending = True
            GLib.idle_add(self._apply_deck_mode, priority=GLib.PRIORITY_HIGH_IDLE)

    def _apply_deck_mode(self) -> bool:
        self._deck_mode_pending = False
        fit = self.deck_fit
        self.deck.set_size_request(fit.width, fit.height)
        if (fit.compact, fit.narrow) == self._deck_mode:
            return False
        self._deck_mode = (fit.compact, fit.narrow)
        for cls, on in (("deck-compact", fit.compact), ("deck-narrow", fit.narrow)):
            if on:
                self.deck.add_css_class(cls)
            else:
                self.deck.remove_css_class(cls)
        self.spectrum.set_content_height(44 if fit.compact else 84)
        self.vol_lab.set_visible(not fit.narrow)
        self.volume.set_size_request(72 if fit.narrow else 110, -1)
        # Thin tiles: tighter gaps so the seek bar keeps a usable length.
        self.transport_box.set_spacing(4 if fit.narrow else 10)
        self.seek.set_size_request(96 if fit.narrow else -1, -1)
        return False

    def _install_header(self) -> None:
        # Hypr draws the 2px square border. GTK CSD was a rounded title strip.
        self.set_decorated(False)

    def _deck_bar(self) -> Gtk.Widget:
        bar = Gtk.Box(spacing=12)
        bar.add_css_class("deck-bar")
        bar.set_valign(Gtk.Align.FILL)
        mark = Gtk.Label(label="Music Player")
        mark.add_css_class("wordmark")
        mark.set_valign(Gtk.Align.CENTER)
        bar.append(mark)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        bar.append(spacer)
        self.btn_account = Gtk.Button(label="Account")
        self.btn_account.add_css_class("flat")
        self.btn_account.add_css_class("home-link")
        self.btn_account.set_valign(Gtk.Align.CENTER)
        self.btn_account.connect("clicked", self._on_account)
        bar.append(self.btn_account)
        return bar

    def _install_icons(self) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            return
        theme = Gtk.IconTheme.get_for_display(display)
        root = Path(__file__).resolve().parent / "icons"
        theme.add_search_path(str(root))

    def _icon_button(self, icon: str, tooltip: str, *, toggle: bool = False, flat: bool = True) -> Gtk.Button:
        btn: Gtk.Button = Gtk.ToggleButton() if toggle else Gtk.Button()
        btn.set_tooltip_text(tooltip)
        alt, mark = _ICON_MARK.get(icon, ("", tooltip[:4].upper()))
        display = Gdk.Display.get_default()
        theme = Gtk.IconTheme.get_for_display(display) if display is not None else None
        name = icon if theme is not None and theme.has_icon(icon) else alt
        if name and theme is not None and theme.has_icon(name):
            btn.set_icon_name(name)
        else:
            btn.set_label(mark)
            btn.add_css_class("mark")
        if flat:
            btn.add_css_class("flat")
        return btn

    def _lcd(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.add_css_class("lcd")
        eyebrow = Gtk.Box()
        live = Gtk.Label(label="youtube music", xalign=0)
        live.add_css_class("artist")
        live.set_hexpand(True)
        eyebrow.append(live)
        box.append(eyebrow)
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True, valign=Gtk.Align.CENTER)
        self.track_title = Gtk.Label(label="Nothing playing", xalign=0)
        self.track_title.add_css_class("marquee")
        self.track_title.set_wrap(False)
        self.track_title.set_lines(1)
        bind_ellipsize(self.track_title, 28)
        self.track_meta = Gtk.Label(label="YouTube Music", xalign=0)
        self.track_meta.add_css_class("artist")
        self.track_meta.set_wrap(False)
        bind_ellipsize(self.track_meta, 40)
        text.append(self.track_title)
        text.append(self.track_meta)
        clock = Gtk.Box(spacing=8, valign=Gtk.Align.END)
        clock.set_hexpand(False)
        self.pos_label = Gtk.Label(label="0:00")
        self.pos_label.add_css_class("clock")
        slash = Gtk.Label(label="/")
        slash.add_css_class("dur")
        self.dur_label = Gtk.Label(label="0:00")
        self.dur_label.add_css_class("dur")
        clock.append(self.pos_label)
        clock.append(slash)
        clock.append(self.dur_label)
        top.append(text)
        top.append(clock)
        box.append(top)
        self.spectrum = SpectrumView()
        self.spectrum.set_content_height(84)
        self.spectrum.on_cycle = self._cycle_vis
        box.append(self.spectrum)
        return box

    def _transport(self) -> Gtk.Widget:
        box = Gtk.Box(spacing=10)
        box.add_css_class("transport")
        self.transport_box = box
        self.btn_prev = self._icon_button("media-skip-backward-symbolic", "Previous", flat=False)
        self.btn_play = self._icon_button("media-playback-start-symbolic", "Play", flat=False)
        self.btn_play.add_css_class("play")
        self.btn_stop = self._icon_button("media-playback-stop-symbolic", "Stop", flat=False)
        self.btn_next = self._icon_button("media-skip-forward-symbolic", "Next", flat=False)
        for btn in (self.btn_prev, self.btn_play, self.btn_stop, self.btn_next):
            btn.add_css_class("tb")
            box.append(btn)
        self.btn_prev.connect("clicked", lambda *_: self._cmd("prev"))
        self.btn_play.connect("clicked", lambda *_: self._cmd("toggle"))
        self.btn_stop.connect("clicked", lambda *_: self._cmd("stop"))
        self.btn_next.connect("clicked", lambda *_: self._cmd("next"))
        self.seek = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 1)
        self.seek.set_draw_value(False)
        self.seek.set_hexpand(True)
        self.seek.connect("change-value", self._on_seek_change)
        self.seek.connect("value-changed", self._on_seek_value)
        click = Gtk.GestureClick()
        click.set_button(0)
        click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click.connect("pressed", lambda *_: self._seek.drag(self.seek.get_value()))
        click.connect("released", self._on_seek_release)
        click.connect("cancel", self._on_seek_release)
        self.seek.add_controller(click)
        box.append(self.seek)
        self.btn_shuf = self._icon_button("media-playlist-shuffle-symbolic", "Shuffle", toggle=True)
        self.btn_rep = self._icon_button("media-playlist-repeat-symbolic", "Repeat off", toggle=True)
        self.btn_auto = self._icon_button("media-playlist-consecutive-symbolic", "Play similar after queue (off)", toggle=True)
        self.btn_sleep = self._icon_button("alarm-symbolic", "Sleep timer off", toggle=True)
        self.btn_like = self._icon_button("music-thumb-up-symbolic", "Like", toggle=True)
        self.btn_like.add_css_class("rate")
        self.btn_sleep.connect("toggled", self._on_sleep_toggle)
        self.btn_like.connect("toggled", self._on_like)
        self.btn_shuf.connect("toggled", self._on_shuffle)
        self.btn_rep.connect("toggled", self._on_repeat)
        self.btn_auto.connect("toggled", self._on_automix)
        for btn in (self.btn_shuf, self.btn_rep, self.btn_auto, self.btn_sleep, self.btn_like):
            box.append(btn)
        vol = Gtk.Box(spacing=8)
        vol_lab = Gtk.Label(label="VOL")
        vol_lab.add_css_class("knob-lbl")
        self.vol_lab = vol_lab
        self.volume = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.volume.set_draw_value(False)
        self.volume.set_size_request(110, -1)
        self.volume.set_tooltip_text("Volume")
        self.volume.connect("value-changed", self._on_volume)
        self.vol_num = Gtk.Label(label="70")
        self.vol_num.add_css_class("vol-num")
        self.vol_num.set_width_chars(3)
        vol.append(vol_lab)
        vol.append(self.volume)
        vol.append(self.vol_num)
        box.append(vol)
        return box

    def _footer(self) -> Gtk.Widget:
        foot = Gtk.Box(spacing=10)
        foot.add_css_class("foot")
        self.status_dot = Gtk.Label(label="●")
        self.status_dot.add_css_class("pulse-off")
        self.status_dot.set_valign(Gtk.Align.CENTER)
        self.status_label = Gtk.Label(label="stopped")
        self.status_label.add_css_class("meta")
        self.status_label.set_xalign(0)
        self.status_label.set_hexpand(True)
        self.status_label.set_valign(Gtk.Align.CENTER)
        foot.append(self.status_dot)
        foot.append(self.status_label)
        return foot

    def _body(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_vexpand(True)
        bar = Gtk.Box(spacing=4)
        bar.add_css_class("tab-caption")
        bar.set_margin_start(8)
        bar.set_margin_end(8)
        self.btn_mode_queue = Gtk.ToggleButton(label="Queue")
        self.btn_mode_library = Gtk.ToggleButton(label="Library")
        for btn in (self.btn_mode_queue, self.btn_mode_library):
            btn.add_css_class("seg")
        self.btn_mode_library.set_group(self.btn_mode_queue)
        self.btn_mode_queue.connect("toggled", lambda b: b.get_active() and self._show_queue())
        self.btn_mode_library.connect("toggled", lambda b: b.get_active() and self._show_library())
        bar.append(self.btn_mode_queue)
        bar.append(self.btn_mode_library)
        find_l = Gtk.Label(label="FIND")
        find_l.add_css_class("find-l")
        self.search_entry = Gtk.Entry()
        self.search_entry.set_placeholder_text("title or artist")
        self.search_entry.set_hexpand(True)
        self.search_entry.add_css_class("find-i")
        self.search_entry.connect("activate", self._on_search)
        bar.append(find_l)
        bar.append(self.search_entry)
        box.append(bar)
        self.body_stack = Gtk.Stack()
        self.body_stack.set_vexpand(True)
        self.body_stack.add_named(self._queue_tab(), "queue")
        self.body_stack.add_named(self._music_tab(), "library")
        box.append(self.body_stack)
        self.notebook = self.body_stack
        self._show_queue()
        return box

    def _sync_mode_buttons(self, mode: str) -> None:
        self._mode_syncing = True
        try:
            self.btn_mode_queue.set_active(mode == "queue")
            self.btn_mode_library.set_active(mode == "library")
        finally:
            self._mode_syncing = False

    def _show_queue(self) -> None:
        if getattr(self, "_mode_syncing", False):
            self.body_stack.set_visible_child_name("queue")
            return
        self.body_stack.set_visible_child_name("queue")
        self._sync_mode_buttons("queue")

    def _show_library(self) -> None:
        if getattr(self, "_mode_syncing", False):
            self.body_stack.set_visible_child_name("library")
            return
        self.body_stack.set_visible_child_name("library")
        self._sync_mode_buttons("library")

    def _list(self) -> Gtk.ListBox:
        widget = Gtk.ListBox()
        widget.set_selection_mode(Gtk.SelectionMode.SINGLE)
        widget.set_activate_on_single_click(False)
        return widget

    def _page(self) -> Gtk.Box:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.add_css_class("tab-page")
        page.set_hexpand(True)
        page.set_vexpand(True)
        page.set_margin_start(8)
        page.set_margin_end(8)
        return page

    def _queue_tab(self) -> Gtk.Widget:
        page = self._page()
        bar, cap_l, cap_r = caption_bar()
        q_lab = Gtk.Label(label="QUEUE", xalign=0)
        q_lab.add_css_class("meta")
        lyr_lab = Gtk.Label(label="LYRICS", xalign=0)
        lyr_lab.add_css_class("meta")
        cap_l.append(q_lab)
        cap_r.append(lyr_lab)
        page.append(bar)
        panes = Gtk.Box(spacing=8, vexpand=True)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left.set_hexpand(True)
        self.queue_empty = Gtk.Label(label="Queue is empty. Open Library and press Enter on a song.")
        self.queue_empty.add_css_class("hint")
        self.queue_empty.set_margin_top(24)
        self.queue_list = self._list()
        self.queue_list.connect("row-activated", self._on_queue_activate)
        drop = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
        drop.connect("drop", self._on_queue_drop)
        self.queue_list.add_controller(drop)
        self.queue_scroll = constrain_scroll(Gtk.ScrolledWindow())
        self.queue_scroll.set_child(self.queue_list)
        left.append(self.queue_empty)
        left.append(self.queue_scroll)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        right.set_hexpand(True)
        self.lyrics_empty = Gtk.Label(label="no lyrics", xalign=0)
        self.lyrics_empty.add_css_class("hint")
        self.lyrics_empty.set_margin_start(8)
        self.lyrics_empty.set_margin_top(8)
        self.lyrics_list = self._list()
        self.lyrics_list.add_css_class("lyrics")
        self.lyrics_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.lyrics_scroll = constrain_scroll(Gtk.ScrolledWindow())
        self.lyrics_scroll.set_child(self.lyrics_list)
        right.append(self.lyrics_empty)
        right.append(self.lyrics_scroll)
        panes.append(left)
        panes.append(right)
        page.append(panes)
        return page

    def _music_tab(self) -> Gtk.Widget:
        page = self._page()
        bar, left, right = caption_bar()
        playlists_lab = Gtk.Label(label="PLAYLISTS", xalign=0)
        playlists_lab.add_css_class("meta")
        self.tracks_label = Gtk.Label(label="TRACKS", xalign=0)
        self.tracks_label.add_css_class("meta")
        bind_ellipsize(self.tracks_label, 42)
        left.append(playlists_lab)
        right.append(self.tracks_label)
        page.append(bar)
        panes = Gtk.Box(spacing=8, vexpand=True)
        col_l = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        col_l.set_hexpand(True)
        self.playlist_list = self._list()
        self.playlist_list.connect("row-selected", self._on_playlist_selected)
        self.playlist_list.connect("row-activated", self._on_playlist_activated)
        pick = Gtk.GestureClick()
        pick.connect("released", self._on_playlist_click)
        self.playlist_list.add_controller(pick)
        left_scroll = constrain_scroll(Gtk.ScrolledWindow())
        left_scroll.set_child(self.playlist_list)
        col_l.append(left_scroll)
        col_r = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        col_r.set_hexpand(True)
        self.track_list = self._list()
        self.track_list.connect("row-activated", self._on_track_activated)
        right_scroll = constrain_scroll(Gtk.ScrolledWindow())
        right_scroll.set_child(self.track_list)
        col_r.append(right_scroll)
        panes.append(col_l)
        panes.append(col_r)
        page.append(panes)
        return page

    def _bind_keys(self) -> None:
        ctrl = Gtk.EventControllerKey()
        ctrl.connect("key-pressed", self._on_key)
        self.add_controller(ctrl)

    def _on_key(self, _c, keyval, _code, state) -> bool:
        mods = state & Gtk.accelerator_get_default_mod_mask()
        if mods & Gdk.ModifierType.CONTROL_MASK and keyval in (Gdk.KEY_q, Gdk.KEY_Q):
            app = self.get_application()
            if app is not None and hasattr(app, "quit_engine"):
                app.quit_engine()
            return True
        if self.search_entry.has_focus():
            if keyval == Gdk.KEY_Escape:
                self.set_focus(None)
                return True
            return False
        if getattr(self, "_help_veil", None) is not None and self._help_veil.get_visible():
            if keyval in (Gdk.KEY_Escape, Gdk.KEY_question):
                self._help_veil.set_visible(False)
            return True
        if keyval == Gdk.KEY_question:
            self._toggle_help()
            return True
        if keyval == Gdk.KEY_Escape:
            self.set_focus(None)
            return True
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_KP_Delete):
            return self._delete_selected_queue_row()
        if keyval == Gdk.KEY_Menu or (
            keyval == Gdk.KEY_F10 and mods & Gdk.ModifierType.SHIFT_MASK
        ):
            self._open_context_menu()
            return True
        if keyval == Gdk.KEY_space:
            self._cmd("toggle")
            return True
        if keyval in (Gdk.KEY_n, Gdk.KEY_N):
            self._cmd("next")
            return True
        if keyval in (Gdk.KEY_p, Gdk.KEY_P):
            self._cmd("prev")
            return True
        if keyval in (Gdk.KEY_s, Gdk.KEY_S):
            self._cmd("stop")
            return True
        if keyval in (Gdk.KEY_l, Gdk.KEY_L):
            self.btn_like.set_active(not self.btn_like.get_active())
            return True
        if keyval == Gdk.KEY_Up:
            self.volume.set_value(min(100, self.volume.get_value() + 5))
            return True
        if keyval == Gdk.KEY_Down:
            self.volume.set_value(max(0, self.volume.get_value() - 5))
            return True
        if keyval in (Gdk.KEY_Left, Gdk.KEY_Right):
            delta = -5 if keyval == Gdk.KEY_Left else 5
            self._queue_cmd({"cmd": "seek", "value": max(0, self.status.position + delta)})
            return True
        if keyval == Gdk.KEY_F11:
            if self.is_fullscreen():
                self.unfullscreen()
            else:
                self.fullscreen()
            return True
        if keyval in (Gdk.KEY_m, Gdk.KEY_M):
            self._show_library()
            return True
        if keyval in (Gdk.KEY_q, Gdk.KEY_Q):
            self._show_queue()
            return True
        if keyval == Gdk.KEY_slash or (
            mods & Gdk.ModifierType.CONTROL_MASK and keyval in (Gdk.KEY_f, Gdk.KEY_F)
        ):
            self.search_entry.grab_focus()
            return True
        return False

    def _apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._css.load_from_data(css_for(palette).encode())
        self.spectrum.set_palette(palette)
        if getattr(self, "field", None) is not None:
            self.field.set_palette(palette)

    def _paint(self) -> None:
        self._apply_palette(self._base_palette)

    def _watch_theme(self) -> None:
        seen: set[str] = set()
        watch = [
            *omarchy_colors_paths(),
            omarchy_state_dir(),
            omarchy_state_dir() / "theme",
            omarchy_state_dir() / "theme.name",
            omarchy_current_dir(),
            omarchy_current_dir() / "theme",
            Path.home() / ".config/omarchy/current",
            Path.home() / ".config/omarchy/current/theme",
        ]
        for path in watch:
            key = str(path)
            if key in seen or not path.exists():
                continue
            seen.add(key)
            monitor = Gio.File.new_for_path(key).monitor(Gio.FileMonitorFlags.WATCH_MOVES, None)
            monitor.connect("changed", self._on_theme_changed)
            self._theme_monitors.append(monitor)
        self._watch_config()

    def _watch_config(self) -> None:
        """Pick up a hand-edited vis_mode in config.toml without a restart."""
        self._config_reload_id = 0
        try:
            folder = config_path().parent
            if not folder.exists():
                return
            monitor = Gio.File.new_for_path(str(folder)).monitor(Gio.FileMonitorFlags.WATCH_MOVES, None)
        except GLib.Error:
            return
        monitor.connect("changed", self._on_config_changed)
        self._theme_monitors.append(monitor)

    def _on_config_changed(self, _monitor, file, other, _event) -> None:
        name = config_path().name
        if (file is None or file.get_basename() != name) and (other is None or other.get_basename() != name):
            return
        if self._config_reload_id:
            GLib.source_remove(self._config_reload_id)
        self._config_reload_id = GLib.timeout_add(150, self._reload_config)

    def _reload_config(self) -> bool:
        self._config_reload_id = 0
        mode = load_vis_mode()
        if mode != getattr(self.spectrum, "mode", None):
            self._apply_vis(mode)
        return False

    def _on_theme_changed(self, *_a) -> None:
        if self._theme_reload_id:
            GLib.source_remove(self._theme_reload_id)
        self._theme_reload_id = GLib.timeout_add(150, self._reload_theme)

    def _reload_theme(self) -> bool:
        self._theme_reload_id = 0
        try:
            self._base_palette = load_active_palette()
            self._paint()
        except (OSError, ValueError):
            pass
        return False

    def _bootstrap(self) -> bool:
        self._async("", lambda: self.ipc.request({"cmd": "auth.status"}, timeout=8), self._got_auth)
        return False

    def _got_auth(self, payload, err) -> bool:
        if err and "unknown command" in err.lower():
            self._load_playlists()
            return False
        if err or (payload and payload.get("logged_in") is False):
            self._fill_login_browsers((payload or {}).get("browsers"))
            self._show_login((payload or {}).get("error") or err or "", watch=True)
            self._set_account_tip(False, "")
            return False
        self._set_account_tip(True, (payload or {}).get("source") or "")
        self._load_playlists()
        return False

    def _set_account_tip(self, logged_in: bool, source: str) -> None:
        if not hasattr(self, "btn_account"):
            return
        if logged_in:
            where = source.replace("firefox:", "").replace("chrome:", "") if source else "this computer"
            self.btn_account.set_tooltip_text(f"Signed in · {where}")
        else:
            self.btn_account.set_tooltip_text("Sign in")

    def _on_account(self, *_a) -> None:
        if getattr(self, "login_veil", None) is not None and self.login_veil.get_visible():
            return
        self._dismiss_menu()
        pop = Gtk.Popover()
        pop.set_has_arrow(True)
        pop.add_css_class("ctx-menu")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(10)
        box.set_margin_end(10)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        source = self.status.auth_source or "this computer"
        lab = Gtk.Label(label=f"Signed in via {source}", xalign=0)
        lab.add_css_class("meta")
        lab.set_wrap(True)
        box.append(lab)
        out = Gtk.Button(label="Sign out")
        out.add_css_class("flat")
        out.connect("clicked", lambda *_: self._sign_out())
        box.append(out)
        pop.set_child(box)
        pop.set_parent(self.btn_account)
        pop.popup()
        self._ctx_pop = pop

    def _sign_out(self) -> None:
        self._dismiss_menu()
        self._async(
            "signing out…",
            lambda: self.ipc.request({"cmd": "auth.logout"}, timeout=8),
            self._got_logout,
        )

    def _got_logout(self, payload, err) -> bool:
        if err:
            self._set_footer(err)
            return False
        self._set_account_tip(False, "")
        self._show_login("Signed out. Click Sign in when you want this app to use the browser account.", watch=False)
        return False

    def _async(self, message, fn, done) -> None:
        if message:
            self._set_footer(message)

        def work() -> None:
            try:
                result = fn()
                err = None
            except Exception as exc:  # noqa: BLE001
                result = None
                err = str(exc)
            GLib.idle_add(done, result, err)

        threading.Thread(target=work, daemon=True).start()

    def _row(self, left: str, mid: str, right: str) -> Gtk.ListBoxRow:
        return make_row(left, mid, right)

    def _clear(self, widget: Gtk.ListBox) -> None:
        clear_list(widget)

    def _pump(self) -> None:
        """The meter, plus a status poll that is only a fallback once subscribed.

        Slow commands run on their own lanes; status changes arrive pushed on the
        subscribe stream (see _subscribe_loop).
        """
        last = 0.0
        last_bands = 0.0
        while not self._pump_stop.is_set():
            now = time.monotonic()
            if now - last_bands >= pump_intervals(self._playing_hint, self._subscribed)[0]:
                try:
                    raw = self.ipc.request({"cmd": "bands"}, timeout=0.8, raise_on_error=False)
                    GLib.idle_add(self._on_bands, raw)
                except OSError:
                    pass
                last_bands = now
            if now - last >= pump_intervals(self._playing_hint, self._subscribed)[1]:
                try:
                    raw = self.ipc.request({"cmd": "status"}, timeout=2.0, raise_on_error=False)
                    GLib.idle_add(self._on_status, raw)
                except OSError:
                    GLib.idle_add(self._note_link_down, "")
                last = now
            self._pump_stop.wait(0.05)

    def _subscribe_loop(self) -> None:
        """Hold a subscribe stream open; reconnect after drops, back off on old engines."""
        def on_event(raw: dict) -> None:
            if raw.get("subscribed"):
                self._subscribed = True
            GLib.idle_add(self._on_status, raw)

        while not self._pump_stop.is_set():
            wait = 1.0
            try:
                result = self.ipc.subscribe(on_event, self._pump_stop)
                if result == "unsupported":
                    wait = 30.0  # an older engine: keep polling, try again later
            except (OSError, ValueError):
                pass
            self._subscribed = False
            self._pump_stop.wait(wait)

    def _command_loop(self, name: str) -> None:
        lane = self._cmd_lanes[name]
        while not self._pump_stop.is_set():
            try:
                payload, timeout = lane.get(timeout=0.05)
            except queue.Empty:
                continue
            self._dispatch_cmd(payload, timeout)

    def _dispatch_cmd(self, payload: dict, timeout: float) -> None:
        try:
            resp = self.ipc.request(payload, timeout=timeout, raise_on_error=False)
            if payload.get("cmd") in {"track.like", "track.unlike"}:
                GLib.idle_add(self._on_like_result, payload, resp)
            elif not resp.get("ok", True):
                GLib.idle_add(self._set_footer, resp.get("error") or "engine error")
            elif payload.get("cmd") == "playlist.add":
                GLib.idle_add(self._set_footer, "saved to playlist")
            elif payload.get("cmd") in {
                "track.play_next",
                "track.queue",
                "queue.move",
                "queue.remove",
                "track.mix",
                "playlist.mix",
            }:
                GLib.idle_add(self._refresh_queue)
        except (OSError, EngineError) as exc:
            GLib.idle_add(self._note_link_down, str(exc))

    def _queue_cmd(self, payload: dict, timeout: float = 20.0) -> None:
        name = lane_for(str(payload.get("cmd") or ""))
        if name == "fast":
            name = "query"
        self._cmd_lanes[name].put((payload, timeout))

    def _cmd(self, name: str) -> None:
        self._queue_cmd({"cmd": name})

    def _on_status(self, raw: dict) -> bool:
        if not raw or not raw.get("ok"):
            return False
        prev = self.status.track.id if self.status.track else ""
        was_in = bool(self.status.logged_in)
        self.status = parse_status(raw)
        self._playing_hint = self.status.state == "playing"
        self._pos_base = (self.status.position, time.monotonic())
        self._apply_status()
        self._sync_pos_timer()
        if self.status.logged_in and not was_in:
            if getattr(self, "login_veil", None) is not None and self.login_veil.get_visible():
                self._hide_login()
            self._set_account_tip(True, self.status.auth_source)
            if not self._playlists:
                self._load_playlists()
        now = self.status.track.id if self.status.track else ""
        if now != prev:
            self._rating_track = now
            self._rating_hold_until = 0.0
            self._set_rating(None)
            self._load_lyrics(now)
        self._engine_seen = True
        if self._footer_kind in {"offline", "reconnect"} or self._footer_text == "starting…":
            self._clear_footer()
        if raw.get("liked") is not None and should_apply_engine_rating(
            hold_until=self._rating_hold_until, now=time.monotonic()
        ):
            self._set_rating(self.status.liked)
        sig = str(raw.get("queue_sig") or "")
        if not self._dragging and sig and sig != self._queue_sig:
            self._queue_sig = sig
            self._refresh_queue()
        return False

    def _sync_pos_timer(self) -> None:
        playing = self.status.state == "playing"
        if playing and not self._pos_timer:
            self._pos_timer = GLib.timeout_add(250, self._tick_position)
        elif not playing and self._pos_timer:
            GLib.source_remove(self._pos_timer)
            self._pos_timer = 0

    def _tick_position(self) -> bool:
        """Between pushed updates, advance the clock locally while playing."""
        st = self.status
        if st.state != "playing":
            self._pos_timer = 0
            return False
        pos = interpolate_position(self._pos_base, time.monotonic(), st.duration)
        if self._seek.follow_status():
            self._syncing = True
            try:
                self.pos_label.set_text(format_time(pos))
                self.seek.set_value(pos)
            finally:
                self._syncing = False
        return True

    def _apply_status(self) -> None:
        st = self.status
        self._syncing = True
        try:
            playing = st.state == "playing"
            self.btn_play.set_icon_name("media-playback-pause-symbolic" if playing else "media-playback-start-symbolic")
            self.btn_play.set_tooltip_text("Pause" if playing else "Play")
            if st.track:
                self.track_title.set_text(st.track.title or "untitled")
                self.track_meta.set_text(f"{st.track.artist or 'unknown'} · {st.track.album or 'YouTube Music'}")
            else:
                self.track_title.set_text("Nothing playing")
                self.track_meta.set_text("YouTube Music")
            if self._notice and time.monotonic() < self._notice_until:
                self.track_meta.set_text(self._notice)
            else:
                self._notice = ""
            self.pos_label.set_text(format_time(st.position) if self._seek.follow_status() else format_time(self.seek.get_value()))
            self.dur_label.set_text(format_time(st.duration))
            self.seek.set_range(0, max(st.duration, 1))
            if self._seek.follow_status():
                self.seek.set_value(st.position)
            self.btn_shuf.set_active(st.shuffle)
            self.btn_rep.set_active(st.repeat != "off")
            rep = {"off": "Repeat off", "all": "Repeat all", "one": "Repeat one"}.get(st.repeat, "Repeat")
            self.btn_rep.set_tooltip_text(rep)
            self.btn_auto.set_active(st.automix)
            self.btn_auto.set_tooltip_text("Play similar after queue" + ("" if st.automix else " (off)"))
            sleeping = st.sleep_remaining > 0
            if not self._sleep_picking:
                self.btn_sleep.set_active(sleeping)
            if sleeping:
                mins = max(1, (st.sleep_remaining + 59) // 60)
                self.btn_sleep.set_tooltip_text(f"Sleep in {mins} min")
            else:
                self.btn_sleep.set_tooltip_text("Sleep timer off")
            self.volume.set_value(st.volume)
            self.vol_num.set_text(str(int(st.volume)))
            self._set_vis_volume(st.volume)
            self._set_account_tip(st.logged_in, st.auth_source)
            if st.track:
                self.set_title(st.track.title or "Music")
            else:
                self.set_title("Music")
            self._paint_footer()
            self.status_dot.remove_css_class("pulse")
            self.status_dot.remove_css_class("pulse-off")
            self.status_dot.add_css_class("pulse" if playing else "pulse-off")
        finally:
            self._syncing = False

    def _refresh_queue(self) -> None:
        def done(payload, err) -> bool:
            if err or not payload or not payload.get("ok", True):
                return False
            tracks = parse_tracks(payload)
            index = int(payload.get("index") if payload.get("index") is not None else -1)
            self._render_queue(tracks, index)
            return False

        self._async("", lambda: self.ipc.request({"cmd": "queue.list"}, timeout=5), done)

    def _on_seek_change(self, _s, _sc, value: float) -> bool:
        self._seek.drag(float(value))
        self.pos_label.set_text(format_time(value))
        self._arm_seek_commit()
        return False

    def _on_seek_value(self, scale: Gtk.Scale) -> None:
        if self._syncing:
            return
        self._seek.drag(scale.get_value())
        self.pos_label.set_text(format_time(scale.get_value()))
        self._arm_seek_commit()

    def _on_seek_release(self, *_args) -> None:
        self._seek.drag(self.seek.get_value())
        self._commit_seek(immediate=True)

    def _arm_seek_commit(self) -> None:
        if self._seek_timer:
            GLib.source_remove(self._seek_timer)
        self._seek_timer = GLib.timeout_add(130, self._commit_seek)

    def _commit_seek(self, immediate: bool = False) -> bool:
        timer = self._seek_timer
        self._seek_timer = 0
        if immediate and timer:
            GLib.source_remove(timer)
        target = self._seek.release() if immediate else self._seek.take_settled()
        if target is None:
            return False
        self._queue_cmd({"cmd": "seek", "value": target})
        return False

    def _on_volume(self, scale: Gtk.Scale) -> None:
        if self._syncing:
            return
        self.vol_num.set_text(str(int(scale.get_value())))
        self._set_vis_volume(scale.get_value())
        self._queue_cmd({"cmd": "volume", "value": scale.get_value()})

    def _set_vis_volume(self, volume: float) -> None:
        """The visualizers calm down and dim with the volume slider."""
        self.spectrum.set_volume(volume)
        if getattr(self, "field", None) is not None:
            self.field.set_volume(volume)

    def _on_shuffle(self, btn: Gtk.ToggleButton) -> None:
        if self._syncing:
            return
        self._queue_cmd({"cmd": "shuffle", "name": "on" if btn.get_active() else "off"})

    def _on_repeat(self, btn: Gtk.ToggleButton) -> None:
        if self._syncing:
            return
        del btn
        self._queue_cmd({"cmd": "repeat", "name": "cycle"})

    def _on_automix(self, btn: Gtk.ToggleButton) -> None:
        if self._syncing:
            return
        self._queue_cmd({"cmd": "automix", "name": "on" if btn.get_active() else "off"})

    def _set_rating(self, liked: bool | None) -> None:
        self._rating_syncing = True
        try:
            self.btn_like.set_active(bool(liked))
            self.btn_like.set_tooltip_text("Unlike" if liked else "Like")
        finally:
            self._rating_syncing = False

    def _on_like(self, btn: Gtk.ToggleButton) -> None:
        if self._rating_syncing:
            return
        tid = self.status.track.id if self.status.track else ""
        if not tid:
            self._set_rating(False)
            return
        liked = bool(btn.get_active())
        self._rating_hold_until = time.monotonic() + 2.5
        self._set_rating(liked)
        self._queue_cmd({"cmd": "track.like" if liked else "track.unlike", "id": tid})

    def _on_like_result(self, payload: dict, resp: dict) -> bool:
        if resp.get("ok"):
            self._set_rating(bool(resp.get("liked")))
            self._rating_hold_until = time.monotonic() + 0.4
            return False
        self._rating_hold_until = 0.0
        self._set_rating(self.status.liked)
        self._show_notice(resp.get("error") or "could not update like")
        return False

    def _on_sleep_toggle(self, btn: Gtk.ToggleButton) -> None:
        if self._syncing:
            return
        if not btn.get_active():
            self._queue_cmd({"cmd": "sleep", "minutes": 0})
            return
        self._sleep_picking = True
        pop = Gtk.Popover()
        pop.set_has_arrow(True)
        row = Gtk.Box(spacing=8)
        row.set_margin_start(10)
        row.set_margin_end(10)
        row.set_margin_top(8)
        row.set_margin_bottom(8)
        lab = Gtk.Label(label="Minutes")
        lab.add_css_class("meta")
        spin = Gtk.SpinButton.new_with_range(1, 240, 5)
        spin.set_value(self._sleep_minutes)
        go = Gtk.Button(label="Start")
        go.add_css_class("flat")

        def start(*_a) -> None:
            self._sleep_minutes = int(spin.get_value())
            self._queue_cmd({"cmd": "sleep", "minutes": self._sleep_minutes})
            self._sleep_picking = False
            pop.popdown()

        def closed(*_a) -> None:
            self._sleep_picking = False
            if self.status.sleep_remaining <= 0:
                self._sync_sleep_off()

        go.connect("clicked", start)
        spin.connect("activate", start)
        row.append(lab)
        row.append(spin)
        row.append(go)
        pop.set_child(row)
        pop.set_parent(btn)
        pop.connect("closed", closed)
        pop.popup()
        spin.grab_focus()

    def _sync_sleep_off(self) -> None:
        if self._syncing:
            return
        if self.status.sleep_remaining <= 0 and self.btn_sleep.get_active():
            self._syncing = True
            self.btn_sleep.set_active(False)
            self._syncing = False

    def _on_queue_activate(self, _l, row: Gtk.ListBoxRow) -> None:
        idx = row.get_index()
        if 0 <= idx < len(self._queue) and not self._queue[idx].playable:
            self._show_notice("Can't play here — YouTube-only")
            return
        self._queue_cmd({"cmd": "queue.play", "index": idx})

    def _render_queue(self, tracks: list[Track], index: int) -> None:
        old_ids = [t.id for t in self._queue]
        new_ids = [t.id for t in tracks]
        self._queue = tracks
        self.queue_empty.set_visible(not tracks)
        if not queue_needs_rebuild(old_ids, new_ids) and self.queue_list.get_first_child() is not None:
            self._mark_current_row(index)
            return
        selected = self.queue_list.get_selected_row()
        sel_idx = selected.get_index() if selected is not None else None
        adj = self.queue_scroll.get_vadjustment()
        pos = adj.get_value() if adj is not None else 0.0
        self._clear(self.queue_list)
        for i, track in enumerate(tracks, start=1):
            row = self._row(f"{i:02d}  {track.title}", track.artist, format_time(track.duration_secs))
            if not track.playable:
                row.add_css_class("unplayable")
            if i - 1 == index:
                row.add_css_class("current-track")
            self._bind_song_menu(row, track, source="queue")
            self._bind_queue_drag(row)
            self.queue_list.append(row)

        def restore() -> bool:
            if adj is not None:
                adj.set_value(pos)
            if sel_idx is not None:
                keep = self.queue_list.get_row_at_index(sel_idx)
                if keep is not None:
                    self.queue_list.select_row(keep)
            return False

        GLib.idle_add(restore)

    def _mark_current_row(self, index: int) -> None:
        row = self.queue_list.get_first_child()
        i = 0
        while row is not None:
            if isinstance(row, Gtk.ListBoxRow):
                if i == index:
                    row.add_css_class("current-track")
                else:
                    row.remove_css_class("current-track")
                if i < len(self._queue) and not self._queue[i].playable:
                    row.add_css_class("unplayable")
                else:
                    row.remove_css_class("unplayable")
                i += 1
            row = row.get_next_sibling()

    def _apply_vis(self, mode: str) -> None:
        if getattr(self, "spectrum", None) is not None:
            self.spectrum.set_mode(mode)
            self.spectrum.on_cycle = self._cycle_vis
        if getattr(self, "field", None) is not None:
            self.field.set_mode(mode)
            self.field.on_cycle = self._cycle_vis

    def _cycle_vis(self) -> None:
        mode = cycle_vis(getattr(self.spectrum, "mode", "bricks"))
        self._apply_vis(mode)
        save_vis_mode(mode)

    def _on_bands(self, raw: dict | None) -> bool:
        bands = [float(x) for x in (raw.get("bands") or [])] if raw and raw.get("ok") else []
        if self.status.state != "playing":
            bands = [0.0] * 10
        self.spectrum.set_bands(bands)
        if getattr(self, "field", None) is not None:
            self.field.set_bands(bands)
        return False

    def _bind_song_menu(self, row: Gtk.ListBoxRow, track: Track, *, source: str) -> None:
        click = Gtk.GestureClick()
        click.set_button(Gdk.BUTTON_SECONDARY)
        click.connect("pressed", lambda g, *_a: self._show_song_menu(row, track, source, g))
        row.add_controller(click)

    def _dismiss_menu(self) -> None:
        if self._ctx_pop is not None:
            self._ctx_pop.popdown()
            self._ctx_pop.unparent()
            self._ctx_pop = None

    def _menu_button(self, label: str, on_click) -> Gtk.Button:
        btn = Gtk.Button(label=label)
        btn.set_halign(Gtk.Align.FILL)
        btn.set_hexpand(True)
        btn.connect("clicked", lambda *_: on_click())
        return btn

    def _fill_song_menu(self, pop: Gtk.Popover, row: Gtk.ListBoxRow, track: Track, source: str) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)

        def run(fn) -> None:
            self._dismiss_menu()
            fn()

        for label in song_menu_actions(source):
            if label == "Start mix":
                box.append(self._menu_button(label, lambda: run(lambda: self._start_mix(track))))
            elif label == "Play next":
                box.append(self._menu_button(label, lambda: run(lambda: self._play_next(track))))
            elif label == "Add to queue":
                box.append(self._menu_button(label, lambda: run(lambda: self._add_to_queue(track))))
            elif label == "Save this track…":
                box.append(self._menu_button(label, lambda: self._show_save_menu(pop, row, track, source)))
            elif label == "Save entire queue…":
                box.append(self._menu_button(label, lambda: self._show_save_queue_menu(pop, row, track, source)))
            elif label == "Remove":
                box.append(self._menu_button(label, lambda: run(lambda: self._remove_from_queue(row.get_index()))))
        pop.set_child(box)

    def _popup_song_menu(self, row: Gtk.ListBoxRow, track: Track, source: str) -> None:
        self._dismiss_menu()
        pop = Gtk.Popover()
        pop.set_has_arrow(False)
        pop.add_css_class("ctx-menu")
        self._fill_song_menu(pop, row, track, source)
        pop.set_parent(row)
        pop.popup()
        self._ctx_pop = pop

    def _show_song_menu(self, row: Gtk.ListBoxRow, track: Track, source: str, gesture: Gtk.GestureClick) -> None:
        self._popup_song_menu(row, track, source)
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)

    def _delete_selected_queue_row(self) -> bool:
        if self.body_stack.get_visible_child_name() != "queue":
            return False
        row = self.queue_list.get_selected_row()
        if row is None:
            return False
        self._remove_from_queue(row.get_index())
        return True

    def _open_context_menu(self) -> None:
        if self.body_stack.get_visible_child_name() == "queue":
            row = self.queue_list.get_selected_row()
            if row is None:
                return
            idx = row.get_index()
            if 0 <= idx < len(self._queue):
                self._popup_song_menu(row, self._queue[idx], "queue")
            return
        row = self.track_list.get_selected_row()
        tracks = self.browse.visible()
        if row is not None and 0 <= row.get_index() < len(tracks):
            self._popup_song_menu(row, tracks[row.get_index()], "library")
            return
        prow = self.playlist_list.get_selected_row()
        if prow is not None and 0 <= prow.get_index() < len(self._playlists):
            self._popup_playlist_menu(prow, self._playlists[prow.get_index()])

    def _toggle_help(self) -> None:
        veil = getattr(self, "_help_veil", None)
        if veil is None:
            return
        veil.set_visible(not veil.get_visible())

    def _help_overlay(self) -> Gtk.Widget:
        veil = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True)
        veil.add_css_class("login-veil")
        veil.set_visible(False)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        card.add_css_class("login-card")
        card.set_halign(Gtk.Align.CENTER)
        card.set_valign(Gtk.Align.CENTER)
        title = Gtk.Label(label="Keys", xalign=0)
        title.add_css_class("title")
        card.append(title)
        for line in HELP_LINES:
            lab = Gtk.Label(label=line, xalign=0)
            lab.add_css_class("hint")
            card.append(lab)
        veil.append(card)
        click = Gtk.GestureClick()
        click.connect("pressed", lambda *_a: veil.set_visible(False))
        veil.add_controller(click)
        self._help_veil = veil
        return veil

    def _show_save_menu(self, pop: Gtk.Popover, row: Gtk.ListBoxRow, track: Track, source: str) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        box.append(
            self._menu_button(
                "← Back",
                lambda: self._restore_song_menu(pop, row, track, source),
            )
        )
        if not self._playlists:
            lab = Gtk.Label(label="no playlists loaded")
            lab.add_css_class("hint")
            lab.set_margin_top(6)
            lab.set_margin_bottom(6)
            box.append(lab)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(80)
        scroll.set_max_content_height(240)
        scroll.set_propagate_natural_height(True)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        for plist in self._playlists:
            inner.append(
                self._menu_button(
                    plist.name,
                    lambda p=plist: self._save_to_playlist(p, track),
                )
            )
        scroll.set_child(inner)
        box.append(scroll)
        pop.set_child(box)

    def _restore_song_menu(self, pop: Gtk.Popover, row: Gtk.ListBoxRow, track: Track, source: str) -> None:
        self._fill_song_menu(pop, row, track, source)

    def _start_mix(self, track: Track) -> None:
        self._show_queue()
        self._queue_cmd({"cmd": "track.mix", "track": track.to_ipc()}, timeout=40)

    def _play_next(self, track: Track) -> None:
        self._queue_cmd({"cmd": "track.play_next", "track": track.to_ipc()})

    def _add_to_queue(self, track: Track) -> None:
        self._queue_cmd({"cmd": "track.queue", "track": track.to_ipc()})

    def _remove_from_queue(self, index: int) -> None:
        self._queue_cmd({"cmd": "queue.remove", "index": index})

    def _save_to_playlist(self, plist: PlaylistInfo, track: Track) -> None:
        self._dismiss_menu()
        self._set_footer(f"saving {track.title} → {plist.name}…")
        self._queue_cmd({"cmd": "playlist.add", "playlist_id": plist.id, "video_id": track.id})

    def _show_save_queue_menu(self, pop: Gtk.Popover, row: Gtk.ListBoxRow, track: Track, source: str) -> None:
        self._fill_save_queue_new(pop, row, track, source).grab_focus()

    def _fill_save_queue_new(self, pop: Gtk.Popover, row: Gtk.ListBoxRow, track: Track, source: str) -> Gtk.Entry:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(10)
        box.set_margin_end(10)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.append(self._menu_button("← Back", lambda: self._restore_song_menu(pop, row, track, source)))
        lab = Gtk.Label(label="New playlist", xalign=0)
        lab.add_css_class("meta")
        entry = Gtk.Entry()
        entry.set_text(default_queue_playlist_name())
        entry.set_placeholder_text("playlist name")
        create = Gtk.Button(label="Create playlist")
        create.add_css_class("flat")

        def create_now(*_a) -> None:
            name = entry.get_text().strip()
            self._dismiss_menu()
            self._save_queue({"name": name} if name else {"name": default_queue_playlist_name()})

        create.connect("clicked", create_now)
        entry.connect("activate", create_now)
        existing = Gtk.Button(label="Add to existing…")
        existing.add_css_class("flat")
        existing.connect("clicked", lambda *_: self._fill_save_queue_existing(pop, row, track, source))
        box.append(lab)
        box.append(entry)
        box.append(create)
        box.append(existing)
        pop.set_child(box)
        return entry

    def _fill_save_queue_existing(self, pop: Gtk.Popover, row: Gtk.ListBoxRow, track: Track, source: str) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        box.append(
            self._menu_button(
                "← New playlist",
                lambda: self._fill_save_queue_new(pop, row, track, source).grab_focus(),
            )
        )
        if not self._playlists:
            lab = Gtk.Label(label="no playlists loaded")
            lab.add_css_class("hint")
            lab.set_margin_top(6)
            lab.set_margin_bottom(6)
            box.append(lab)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(80)
        scroll.set_max_content_height(240)
        scroll.set_propagate_natural_height(True)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        for plist in self._playlists:
            inner.append(
                self._menu_button(
                    plist.name,
                    lambda p=plist: self._save_queue({"playlist_id": p.id, "name": p.name}),
                )
            )
        scroll.set_child(inner)
        box.append(scroll)
        pop.set_child(box)

    def _save_queue(self, payload: dict) -> None:
        self._dismiss_menu()
        if not self._queue:
            self._set_footer("queue is empty")
            return
        label = payload.get("name") or "playlist"
        self._async(
            f"saving queue → {label}…",
            lambda: self.ipc.request({"cmd": "queue.save", **payload}, timeout=60),
            lambda result, err: self._got_queue_save(result, err, label),
        )

    def _got_queue_save(self, payload, err, label: str) -> bool:
        if err:
            self._set_footer(err)
            return False
        total = int((payload or {}).get("total") or 0)
        name = (payload or {}).get("name") or label
        self._set_footer(f"saved {total} tracks → {name}")
        if (payload or {}).get("created"):
            self._load_playlists()
        return False

    def _bind_queue_drag(self, row: Gtk.ListBoxRow) -> None:
        source = Gtk.DragSource()
        source.set_actions(Gdk.DragAction.MOVE)
        source.connect("prepare", lambda *_a: self._on_drag_prepare(row))
        source.connect("drag-begin", lambda *_a: self._mark_dragging(True))
        source.connect("drag-end", lambda *_a: self._mark_dragging(False))
        row.add_controller(source)

    def _on_drag_prepare(self, row: Gtk.ListBoxRow):
        self._drag_from = row.get_index()
        self._mark_dragging(True)
        return Gdk.ContentProvider.new_for_value(str(self._drag_from))

    def _mark_dragging(self, active: bool) -> None:
        self._dragging = active
        if not active:
            self._drag_from = None

    def _on_queue_drop(self, _target, _value, _x, y: float) -> bool:
        src = self._drag_from
        self._mark_dragging(False)
        if src is None:
            return False
        dest_row = self.queue_list.get_row_at_y(int(y))
        dest = dest_row.get_index() if dest_row is not None else len(self._queue) - 1
        if dest < 0 or dest == src:
            return True
        self._queue_cmd({"cmd": "queue.move", "from": src, "to": dest})
        item = self._queue.pop(src)
        self._queue.insert(dest, item)
        current = self.status.index
        if current == src:
            current = dest
        elif src < current <= dest:
            current -= 1
        elif dest <= current < src:
            current += 1
        self._render_queue(self._queue, current)
        return True

    def _show_notice(self, text: str, seconds: float = 6.0) -> None:
        self._notice = (text or "").strip()
        self._notice_until = time.monotonic() + max(1.0, seconds)
        if self._notice:
            self.track_meta.set_text(self._notice)

    def _link_message(self) -> str:
        app = self.get_application()
        supervisor = getattr(app, "supervisor", None) if app is not None else None
        proc = getattr(supervisor, "proc", None)
        if proc is not None and proc.poll() is not None:
            detail = ""
            if hasattr(supervisor, "stderr_text"):
                detail = supervisor.stderr_text()
            return detail or "offline"
        if self._engine_seen:
            return "reconnecting…"
        return "starting…"

    def _note_link_down(self, detail: str = "") -> bool:
        text = (detail or "").strip()
        if text and footer_kind(text) == "error" and "died" not in text.lower() and "unreachable" not in text.lower():
            self._set_footer(text)
            return False
        message = self._link_message()
        if message not in {"starting…", "reconnecting…", "offline"}:
            self._cancel_footer_timer()
            self._footer_text = message
            self._footer_kind = "offline"
            self._paint_footer()
            return False
        self._set_footer(message)
        return False

    def _cancel_footer_timer(self) -> None:
        if self._footer_timer:
            GLib.source_remove(self._footer_timer)
            self._footer_timer = 0

    def _clear_footer(self) -> bool:
        self._footer_timer = 0
        self._footer_text = ""
        self._footer_kind = "idle"
        self._paint_footer()
        return False

    def _paint_footer(self) -> None:
        label = self.status_label
        for name in ("foot-note", "foot-progress", "foot-error", "foot-offline", "foot-session", "foot-reconnect"):
            label.remove_css_class(name)
        if self._footer_text and self._footer_kind != "idle":
            label.set_text(self._footer_text)
            label.add_css_class(f"foot-{self._footer_kind}")
            return
        label.set_text(playback_word(self.status.state))

    def _set_footer(self, text: str) -> None:
        message = (text or "").strip()
        if message and is_login_error(message) and "session expired" not in message.lower():
            self._show_login(message)
            return
        low = message.lower()
        if message and ("can't play" in low or "unplayable" in low):
            self._show_notice("Can't play here — YouTube-only")
            message = "Can't play here — YouTube-only"
        if not message:
            self._cancel_footer_timer()
            self._clear_footer()
            return
        kind = footer_kind(message)
        self._cancel_footer_timer()
        self._footer_text = message
        self._footer_kind = kind
        self._paint_footer()
        if kind == "error":
            self._footer_timer = GLib.timeout_add(6000, self._clear_footer)
        elif kind == "note":
            self._footer_timer = GLib.timeout_add(4000, self._clear_footer)

    def _show_lyrics(self, lines: list[str], *, found: bool) -> None:
        self._lyric_lines = [str(line) for line in lines or []]
        self._clear(self.lyrics_list)
        for text in self._lyric_lines:
            lab = Gtk.Label(label=text if text else " ", xalign=0)
            lab.set_wrap(True)
            lab.add_css_class("lyric-line")
            item = Gtk.ListBoxRow()
            item.set_activatable(False)
            item.set_selectable(False)
            item.set_child(lab)
            self.lyrics_list.append(item)
        has = bool(found and self._lyric_lines)
        self.lyrics_list.set_visible(has)
        self.lyrics_empty.set_text("no lyrics")
        self.lyrics_empty.set_visible(not has)

    def _load_lyrics(self, track_id: str) -> None:
        tid = (track_id or "").strip()
        if not tid:
            self._lyrics_id = ""
            self._show_lyrics([], found=False)
            return
        if tid == self._lyrics_id and self._lyric_lines:
            return
        self._lyrics_id = tid
        self._lyrics_token += 1
        token = self._lyrics_token
        self.lyrics_empty.set_text("…")
        self.lyrics_empty.set_visible(True)
        self.lyrics_list.set_visible(False)
        self._async(
            "",
            lambda: self.ipc.request({"cmd": "lyrics", "id": tid}, timeout=20),
            lambda payload, err: self._got_lyrics(token, payload, err),
        )

    def _got_lyrics(self, token: int, payload, err) -> bool:
        if token != self._lyrics_token:
            return False
        if err:
            if is_login_error(err):
                self._set_footer(err)
            self._show_lyrics([], found=False)
            return False
        if not payload or not payload.get("ok"):
            self._show_lyrics([], found=False)
            return False
        self._show_lyrics(lyric_lines(payload), found=bool(payload.get("found")))
        return False


