"""Builds the deck: bar, LCD, transport row, body tabs and footer, and sizes it to the window."""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, GLib, GObject, Gtk

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
from .widgets.field import FieldView
from .widgets.spectrum import SpectrumView

_ICON_MARK = {
    "media-skip-backward-symbolic": ("go-previous-symbolic", "PREV"),
    "media-skip-forward-symbolic": ("go-next-symbolic", "NEXT"),
    "media-playlist-shuffle-symbolic": ("", "SHUF"),
    "media-playlist-consecutive-symbolic": ("", "MIX"),
    "alarm-symbolic": ("", "SLEEP"),
}


class DeckMixin:
    """PlayerWindow methods; state lives on the window (see PlayerWindow.__init__)."""

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

    def _row(self, left: str, mid: str, right: str) -> Gtk.ListBoxRow:
        return make_row(left, mid, right)

    def _clear(self, widget: Gtk.ListBox) -> None:
        clear_list(widget)
