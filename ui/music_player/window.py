from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from urllib.request import urlopen

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango

from .ipc import EngineError, EngineIPC
from .models import PlaylistInfo, PlayerStatus, SeekGate, Track, art_url_for, format_time, parse_playlists, parse_status, parse_tracks
from .theme import PALETTES, Palette, css_for, load_omarchy_palette, palette_named
from .widgets.spectrum import SpectrumView

EQ_LABELS = ["60", "170", "310", "600", "1k", "3k", "6k", "12k", "14k", "16k"]
EQ_PRESETS = [("FLAT", "Flat"), ("ROCK", "Rock"), ("JAZZ", "Jazz"), ("VOCAL", "Pop"), ("BASS", "Bass Boost")]


class PlayerWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application, ipc: EngineIPC):
        super().__init__(application=app, title="MUSIC")
        self.set_default_size(920, 720)
        self.add_css_class("app-window")
        self.ipc = ipc
        self.status = PlayerStatus()
        self._syncing = False
        self._eq_sending = False
        self._seek = SeekGate()
        self._palette = palette_named("mint")
        self._css = Gtk.CssProvider()
        self._art_token = 0
        self._queue: list[Track] = []
        self._playlists: list[PlaylistInfo] = []
        self._lib_tracks: list[Track] = []
        self._search_tracks: list[Track] | None = None
        self._cmd_q: queue.Queue = queue.Queue()
        self._pump_stop = threading.Event()

        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            self._css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        self._build()
        self._apply_palette(self._palette)
        self._bind_keys()
        threading.Thread(target=self._pump, daemon=True).start()
        GLib.idle_add(self._bootstrap)

    def stop_pump(self) -> None:
        self._pump_stop.set()

    def _build(self) -> None:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(root)
        root.append(self._header())
        root.append(self._now_playing())
        self.spectrum = SpectrumView()
        wrap = Gtk.Box()
        wrap.add_css_class("chrome")
        wrap.append(self.spectrum)
        root.append(wrap)
        root.append(self._transport())
        root.append(self._tabs())
        root.append(self._footer())

    def _header(self) -> Gtk.Widget:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        bar.add_css_class("chrome")
        brand = Gtk.Label(label="MUSIC", xalign=0)
        brand.add_css_class("brand")
        self.subtitle = Gtk.Label(label="YouTube Music", hexpand=True)
        self.subtitle.add_css_class("subtitle")
        swatches = Gtk.Box(spacing=6)
        palettes = list(PALETTES)
        omarchy = Path.home() / ".config/omarchy/current/theme/colors.toml"
        if omarchy.is_file():
            try:
                palettes[1] = load_omarchy_palette(omarchy)
            except OSError:
                pass
        for palette in palettes[:4]:
            btn = Gtk.Button()
            btn.add_css_class("swatch")
            btn.connect("clicked", lambda _b, p=palette: self._apply_palette(p))
            css = Gtk.CssProvider()
            css.load_from_data(f"button {{ background: {palette.accent}; }}".encode())
            btn.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            swatches.append(btn)
        bar.append(brand)
        bar.append(self.subtitle)
        bar.append(swatches)
        return bar

    def _now_playing(self) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        row.add_css_class("chrome")
        self.art = Gtk.Picture()
        self.art.set_size_request(88, 88)
        self.art.set_content_fit(Gtk.ContentFit.COVER)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER, hexpand=True)
        self.track_title = Gtk.Label(label="nothing playing", xalign=0)
        self.track_title.add_css_class("title")
        self.track_title.set_ellipsize(Pango.EllipsizeMode.END)
        self.track_meta = Gtk.Label(label="youtube music", xalign=0)
        self.track_meta.add_css_class("meta")
        text.append(self.track_title)
        text.append(self.track_meta)
        row.append(self.art)
        row.append(text)
        return row

    def _transport(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.add_css_class("chrome")
        seek_row = Gtk.Box(spacing=8)
        self.pos_label = Gtk.Label(label="0:00")
        self.pos_label.add_css_class("meta")
        self.seek = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 1)
        self.seek.set_draw_value(False)
        self.seek.set_hexpand(True)
        self.seek.connect("change-value", self._on_seek_change)
        self.seek.connect("value-changed", self._on_seek_value)
        click = Gtk.GestureClick()
        click.set_button(0)
        click.connect("pressed", lambda *_: self._seek.drag(self.seek.get_value()))
        click.connect("released", self._on_seek_release)
        self.seek.add_controller(click)
        self.dur_label = Gtk.Label(label="0:00")
        self.dur_label.add_css_class("meta")
        seek_row.append(self.pos_label)
        seek_row.append(self.seek)
        seek_row.append(self.dur_label)

        controls = Gtk.Box(spacing=6)
        self.btn_prev = Gtk.Button(label="|<")
        self.btn_play = Gtk.Button(label=">")
        self.btn_stop = Gtk.Button(label="[]")
        self.btn_next = Gtk.Button(label=">|")
        self.btn_shuf = Gtk.ToggleButton(label="SHUF")
        self.btn_rep = Gtk.ToggleButton(label="REP")
        self.btn_prev.connect("clicked", lambda *_: self._cmd("prev"))
        self.btn_play.connect("clicked", lambda *_: self._cmd("toggle"))
        self.btn_stop.connect("clicked", lambda *_: self._cmd("stop"))
        self.btn_next.connect("clicked", lambda *_: self._cmd("next"))
        self.btn_shuf.connect("toggled", self._on_shuffle)
        self.btn_rep.connect("toggled", self._on_repeat)
        for btn in (self.btn_prev, self.btn_play, self.btn_stop, self.btn_next, self.btn_shuf, self.btn_rep):
            controls.append(btn)
        vol_box = Gtk.Box(spacing=8, hexpand=True, halign=Gtk.Align.END)
        vol_lab = Gtk.Label(label="VOL")
        vol_lab.add_css_class("meta")
        self.volume = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.volume.set_draw_value(False)
        self.volume.set_size_request(140, -1)
        self.volume.connect("value-changed", self._on_volume)
        self.vol_num = Gtk.Label(label="70")
        self.vol_num.add_css_class("meta")
        vol_box.append(vol_lab)
        vol_box.append(self.volume)
        vol_box.append(self.vol_num)
        controls.append(vol_box)
        box.append(seek_row)
        box.append(controls)
        return box

    def _tabs(self) -> Gtk.Widget:
        self.notebook = Gtk.Notebook()
        self.notebook.set_vexpand(True)
        self.notebook.append_page(self._queue_tab(), Gtk.Label(label="QUEUE"))
        self.notebook.append_page(self._eq_tab(), Gtk.Label(label="EQUALIZER"))
        self.notebook.append_page(self._music_tab(), Gtk.Label(label="MUSIC"))
        return self.notebook

    def _list(self) -> Gtk.ListBox:
        widget = Gtk.ListBox()
        widget.set_selection_mode(Gtk.SelectionMode.SINGLE)
        widget.set_activate_on_single_click(False)
        return widget

    def _queue_tab(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        hint = Gtk.Label(label="up next · enter / double-click to jump", xalign=1)
        hint.add_css_class("hint")
        hint.set_margin_end(10)
        hint.set_margin_top(4)
        self.queue_empty = Gtk.Label(label="Queue is empty. Open MUSIC and press Enter on a song.")
        self.queue_empty.add_css_class("hint")
        self.queue_empty.set_margin_top(24)
        self.queue_list = self._list()
        self.queue_list.connect("row-activated", self._on_queue_activate)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_child(self.queue_list)
        box.append(hint)
        box.append(self.queue_empty)
        box.append(scroll)
        return box

    def _eq_tab(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(10)
        box.set_margin_start(16)
        box.set_margin_end(16)
        presets = Gtk.Box(spacing=8)
        self._eq_preset_btns: dict[str, Gtk.ToggleButton] = {}
        for label, name in EQ_PRESETS:
            btn = Gtk.ToggleButton(label=label)
            btn.connect("toggled", self._on_eq_preset, name)
            presets.append(btn)
            self._eq_preset_btns[name] = btn
        sliders = Gtk.Box(spacing=10, homogeneous=True, vexpand=True)
        self._eq_scales: list[Gtk.Scale] = []
        for label in EQ_LABELS:
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            val = Gtk.Label(label="0")
            val.add_css_class("meta")
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, -12, 12, 0.5)
            scale.set_inverted(True)
            scale.set_draw_value(False)
            scale.set_vexpand(True)
            scale.connect("value-changed", self._on_eq_band)
            name = Gtk.Label(label=label)
            name.add_css_class("meta")
            col.append(val)
            col.append(scale)
            col.append(name)
            sliders.append(col)
            self._eq_scales.append(scale)
            scale._value_label = val  # type: ignore[attr-defined]
        box.append(presets)
        box.append(sliders)
        return box

    def _music_tab(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(8)
        box.set_margin_start(8)
        box.set_margin_end(8)
        search_row = Gtk.Box(spacing=8)
        self.search_entry = Gtk.Entry()
        self.search_entry.set_placeholder_text("search youtube music")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("activate", self._on_search)
        go = Gtk.Button(label="SEARCH")
        go.connect("clicked", self._on_search)
        search_row.append(self.search_entry)
        search_row.append(go)
        panes = Gtk.Box(spacing=8, vexpand=True)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        left_lab = Gtk.Label(label="PLAYLISTS", xalign=0)
        left_lab.add_css_class("meta")
        self.playlist_list = self._list()
        self.playlist_list.connect("row-selected", self._on_playlist_selected)
        self.playlist_list.connect("row-activated", self._on_playlist_activated)
        left_scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        left_scroll.set_child(self.playlist_list)
        left.append(left_lab)
        left.append(left_scroll)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.tracks_label = Gtk.Label(label="TRACKS  ·  enter / double-click to play", xalign=0)
        self.tracks_label.add_css_class("meta")
        self.track_list = self._list()
        self.track_list.connect("row-activated", self._on_track_activated)
        right_scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        right_scroll.set_child(self.track_list)
        right.append(self.tracks_label)
        right.append(right_scroll)
        panes.append(left)
        panes.append(right)
        box.append(search_row)
        box.append(panes)
        return box

    def _footer(self) -> Gtk.Widget:
        bar = Gtk.Box(spacing=16)
        bar.add_css_class("footer")
        self.codec = Gtk.Label(label="YT MUSIC", xalign=0)
        self.codec.add_css_class("codec")
        self.backend = Gtk.Label(label="mpv", xalign=0)
        self.backend.add_css_class("meta")
        self.footer_msg = Gtk.Label(label="space play · enter play · e eq · m music", hexpand=True)
        self.footer_msg.add_css_class("hint")
        bar.append(self.codec)
        bar.append(self.backend)
        bar.append(self.footer_msg)
        return bar

    def _bind_keys(self) -> None:
        ctrl = Gtk.EventControllerKey()
        ctrl.connect("key-pressed", self._on_key)
        self.add_controller(ctrl)

    def _on_key(self, _c, keyval, _code, state) -> bool:
        if self.search_entry.has_focus():
            return False
        if keyval == Gdk.KEY_space:
            self._cmd("toggle")
            return True
        if keyval in (Gdk.KEY_Left, Gdk.KEY_Right):
            delta = -5 if keyval == Gdk.KEY_Left else 5
            self._queue_cmd({"cmd": "seek", "value": max(0, self.status.position + delta)})
            return True
        if keyval in (Gdk.KEY_e, Gdk.KEY_E):
            self.notebook.set_current_page(1)
            return True
        if keyval in (Gdk.KEY_m, Gdk.KEY_M):
            self.notebook.set_current_page(2)
            return True
        mods = state & Gtk.accelerator_get_default_mod_mask()
        if mods & Gdk.ModifierType.CONTROL_MASK and keyval in (Gdk.KEY_f, Gdk.KEY_F):
            self.notebook.set_current_page(2)
            self.search_entry.grab_focus()
            return True
        return False

    def _apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._css.load_from_data(css_for(palette).encode())
        self.spectrum.set_palette(palette)

    def _bootstrap(self) -> bool:
        self._async("loading playlists…", lambda: self.ipc.request({"cmd": "playlists"}, timeout=30), self._got_playlists)
        return False

    def _async(self, message, fn, done) -> None:
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

    def _got_playlists(self, payload, err) -> bool:
        if err:
            self._set_footer(err)
            return False
        self._playlists = parse_playlists(payload or {})
        self._fill(self.playlist_list, [(p.name, "ytmusic", str(p.track_count or "")) for p in self._playlists])
        self.subtitle.set_text(f"YouTube Music — {len(self._playlists)} playlists")
        self._set_footer(f"{len(self._playlists)} playlists · click to browse · enter to play")
        if self._playlists:
            row = self.playlist_list.get_row_at_index(0)
            if row:
                self.playlist_list.select_row(row)
        return False

    def _fill(self, widget: Gtk.ListBox, rows: list[tuple[str, str, str]]) -> None:
        self._clear(widget)
        for left, mid, right in rows:
            widget.append(self._row(left, mid, right))

    def _row(self, left: str, mid: str, right: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        box = Gtk.Box(spacing=12)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(5)
        box.set_margin_bottom(5)
        a = Gtk.Label(label=left, xalign=0, hexpand=True)
        a.set_ellipsize(Pango.EllipsizeMode.END)
        b = Gtk.Label(label=mid, xalign=0)
        b.add_css_class("meta")
        b.set_width_chars(12)
        c = Gtk.Label(label=right, xalign=1)
        c.add_css_class("meta")
        box.append(a)
        box.append(b)
        box.append(c)
        row.set_child(box)
        return row

    def _clear(self, widget: Gtk.ListBox) -> None:
        child = widget.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            widget.remove(child)
            child = nxt

    def _pump(self) -> None:
        last = 0.0
        while not self._pump_stop.is_set():
            try:
                payload, timeout = self._cmd_q.get(timeout=0.05)
            except queue.Empty:
                payload = None
            if payload is not None:
                try:
                    resp = self.ipc.request(payload, timeout=timeout, raise_on_error=False)
                    if not resp.get("ok", True):
                        GLib.idle_add(self._set_footer, resp.get("error") or "engine error")
                except (OSError, EngineError) as exc:
                    GLib.idle_add(self._set_footer, str(exc))
            now = time.monotonic()
            if now - last >= 0.25:
                try:
                    raw = self.ipc.request({"cmd": "status"}, timeout=2.0, raise_on_error=False)
                    GLib.idle_add(self._on_status, raw)
                except OSError:
                    GLib.idle_add(self._set_footer, "engine died")
                last = now

    def _queue_cmd(self, payload: dict, timeout: float = 20.0) -> None:
        self._cmd_q.put((payload, timeout))

    def _cmd(self, name: str) -> None:
        self._queue_cmd({"cmd": name})

    def _on_status(self, raw: dict) -> bool:
        if not raw or not raw.get("ok"):
            return False
        prev = self.status.track.id if self.status.track else ""
        self.status = parse_status(raw)
        self._apply_status()
        now = self.status.track.id if self.status.track else ""
        if now != prev:
            self._refresh_queue()
            self._load_art(self.status.track)
        return False

    def _apply_status(self) -> None:
        st = self.status
        self._syncing = True
        try:
            playing = st.state == "playing"
            self.btn_play.set_label("||" if playing else ">")
            if st.track:
                self.track_title.set_text(("▶ " if playing else "") + (st.track.title or "untitled"))
                self.track_meta.set_text(f"{st.track.artist or 'unknown'} · {st.track.album or 'youtube music'}")
            else:
                self.track_title.set_text("nothing playing")
                self.track_meta.set_text("youtube music")
            self.pos_label.set_text(format_time(st.position))
            self.dur_label.set_text(format_time(st.duration))
            if self._seek._pending is None:
                self.seek.set_range(0, max(st.duration, 1))
                self.seek.set_value(st.position)
            self.btn_shuf.set_active(st.shuffle)
            self.btn_rep.set_active(st.repeat != "off")
            self.volume.set_value(st.volume)
            self.vol_num.set_text(str(int(st.volume)))
            if st.total:
                self.subtitle.set_text(f"YouTube Music — {st.total} in queue")
            self._sync_eq(st)
        finally:
            self._syncing = False

    def _sync_eq(self, st: PlayerStatus) -> None:
        self._eq_sending = True
        try:
            for i, scale in enumerate(self._eq_scales):
                if i < len(st.eq_bands):
                    scale.set_value(st.eq_bands[i])
                    scale._value_label.set_text(f"{st.eq_bands[i]:+.0f}")  # type: ignore[attr-defined]
            for name, btn in self._eq_preset_btns.items():
                btn.set_active(st.eq_preset.lower() == name.lower())
        finally:
            self._eq_sending = False

    def _refresh_queue(self) -> None:
        try:
            raw = self.ipc.request({"cmd": "queue.list"}, timeout=5)
        except (EngineError, OSError):
            return
        tracks = parse_tracks(raw)
        index = int(raw.get("index") if raw.get("index") is not None else -1)
        self._queue = tracks
        self.queue_empty.set_visible(not tracks)
        self._clear(self.queue_list)
        for i, track in enumerate(tracks, start=1):
            row = self._row(f"{i:02d}  {track.title}", track.artist, format_time(track.duration_secs))
            if i - 1 == index:
                row.add_css_class("current-track")
            self.queue_list.append(row)

    def _on_seek_change(self, _s, _sc, value: float) -> bool:
        self._seek.drag(float(value))
        self.pos_label.set_text(format_time(value))
        return False

    def _on_seek_value(self, scale: Gtk.Scale) -> None:
        if self._syncing or self._seek._pending is None:
            return
        self._seek.drag(scale.get_value())
        self.pos_label.set_text(format_time(scale.get_value()))

    def _on_seek_release(self, *_args) -> None:
        self._seek.drag(self.seek.get_value())
        target = self._seek.release(current=self.status.position)
        if target is None:
            return
        self._queue_cmd({"cmd": "seek", "value": target})

    def _on_volume(self, scale: Gtk.Scale) -> None:
        if self._syncing:
            return
        self.vol_num.set_text(str(int(scale.get_value())))
        self._queue_cmd({"cmd": "volume", "value": scale.get_value()})

    def _on_shuffle(self, btn: Gtk.ToggleButton) -> None:
        if self._syncing:
            return
        self._queue_cmd({"cmd": "shuffle", "name": "on" if btn.get_active() else "off"})

    def _on_repeat(self, btn: Gtk.ToggleButton) -> None:
        if self._syncing:
            return
        self._queue_cmd({"cmd": "repeat", "name": "all" if btn.get_active() else "off"})

    def _on_eq_preset(self, btn: Gtk.ToggleButton, name: str) -> None:
        if self._eq_sending or not btn.get_active():
            return
        self._queue_cmd({"cmd": "eq", "name": name})

    def _on_eq_band(self, scale: Gtk.Scale) -> None:
        if self._eq_sending:
            return
        idx = self._eq_scales.index(scale)
        scale._value_label.set_text(f"{scale.get_value():+.0f}")  # type: ignore[attr-defined]
        self._queue_cmd({"cmd": "eq", "band": idx, "value": scale.get_value()})

    def _on_queue_activate(self, _l, row: Gtk.ListBoxRow) -> None:
        self._queue_cmd({"cmd": "queue.play", "index": row.get_index()})

    def _on_playlist_selected(self, _l, row: Gtk.ListBoxRow | None) -> None:
        if row is None or self._search_tracks is not None:
            return
        idx = row.get_index()
        if idx >= len(self._playlists):
            return
        plist = self._playlists[idx]
        self.tracks_label.set_text(f"{plist.name.upper()}  ·  enter / double-click to play")
        self._async(
            f"loading {plist.name}…",
            lambda: self.ipc.request({"cmd": "playlist.tracks", "id": plist.id}, timeout=40),
            self._got_tracks,
        )

    def _got_tracks(self, payload, err) -> bool:
        if err:
            self._set_footer(err)
            return False
        self._lib_tracks = parse_tracks(payload or {})
        if self._search_tracks is None:
            self._render_tracks(self._lib_tracks)
        self._set_footer(f"{len(self._lib_tracks)} tracks")
        return False

    def _render_tracks(self, tracks: list[Track]) -> None:
        self._fill(
            self.track_list,
            [(f"{i:02d}  {t.title}", t.artist, format_time(t.duration_secs)) for i, t in enumerate(tracks, start=1)],
        )

    def _on_playlist_activated(self, _l, row: Gtk.ListBoxRow) -> None:
        idx = row.get_index()
        if idx >= len(self._playlists):
            return
        plist = self._playlists[idx]
        self._set_footer(f"starting {plist.name}…")
        self._queue_cmd({"cmd": "playlist.play", "id": plist.id}, timeout=40)

    def _on_track_activated(self, _l, row: Gtk.ListBoxRow) -> None:
        tracks = self._search_tracks if self._search_tracks is not None else self._lib_tracks
        idx = row.get_index()
        if idx >= len(tracks):
            return
        track = tracks[idx]
        self._set_footer(f"starting {track.title}…")
        self._queue_cmd({"cmd": "track.play", "track": track.to_ipc()}, timeout=30)

    def _on_search(self, *_a) -> None:
        query = self.search_entry.get_text().strip()
        if not query:
            self._search_tracks = None
            self._render_tracks(self._lib_tracks)
            return
        self.tracks_label.set_text(f"SEARCH · {query}")
        self._async(
            f"searching {query}…",
            lambda: self.ipc.request({"cmd": "search", "query": query, "limit": 20}, timeout=20),
            self._got_search,
        )

    def _got_search(self, payload, err) -> bool:
        if err:
            self._set_footer(err)
            return False
        self._search_tracks = parse_tracks(payload or {})
        self._render_tracks(self._search_tracks)
        self._set_footer(f"{len(self._search_tracks)} results")
        return False

    def _set_footer(self, text: str) -> None:
        self.footer_msg.set_text(text)

    def _load_art(self, track: Track | None) -> None:
        self._art_token += 1
        token = self._art_token
        url = art_url_for(track)
        if not url:
            return

        def work() -> None:
            pix = None
            try:
                with urlopen(url, timeout=8) as resp:
                    data = resp.read()
                loader = GdkPixbuf.PixbufLoader()
                loader.write(data)
                loader.close()
                pix = loader.get_pixbuf()
                if pix is not None:
                    pix = pix.scale_simple(88, 88, GdkPixbuf.InterpType.BILINEAR)
            except Exception:
                pix = None
            GLib.idle_add(self._set_art, token, pix)

        threading.Thread(target=work, daemon=True).start()

    def _set_art(self, token: int, pix) -> bool:
        if token != self._art_token or pix is None:
            return False
        self.art.set_pixbuf(pix)
        return False


