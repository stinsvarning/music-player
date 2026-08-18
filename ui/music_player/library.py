from __future__ import annotations

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, Gtk

from .models import (
    can_autoselect_playlist,
    format_time,
    page_done,
    parse_playlists,
    parse_tracks,
    playlist_menu_actions,
    tracks_caption,
)


class LibraryMixin:
    def _is_searching(self) -> bool:
        return self.browse.search_tracks is not None or bool(self.search_entry.get_text().strip())

    def _load_playlists(self) -> None:
        self._playlists_token = getattr(self, "_playlists_token", 0) + 1
        token = self._playlists_token
        self._playlists = []
        self._clear(self.playlist_list)
        self._async(
            "loading playlists…",
            lambda: self.ipc.request({"cmd": "playlists"}, timeout=30),
            lambda payload, err: self._got_playlists(token, payload, err),
        )

    def _got_playlists(self, token: int, payload, err) -> bool:
        if token != getattr(self, "_playlists_token", 0):
            return False
        if err:
            self._set_footer(err)
            return False
        page = parse_playlists(payload or {})
        first = not self._playlists
        self._playlists.extend(page)
        for plist in page:
            self.playlist_list.append(self._playlist_row(plist))
        if can_autoselect_playlist(first=first and bool(self._playlists), searching=self._is_searching()):
            row = self.playlist_list.get_row_at_index(0)
            if row:
                self.playlist_list.select_row(row)
        if page_done(payload):
            if not self._playlists:
                self._set_footer("no playlists")
            elif first:
                self._set_footer("")
            return False
        self._set_footer(f"{len(self._playlists)} playlists…")
        self._async(
            "",
            lambda: self.ipc.request({"cmd": "playlists.more"}, timeout=30),
            lambda more, more_err: self._got_playlists(token, more, more_err),
        )
        return False

    def _playlist_row(self, plist) -> Gtk.ListBoxRow:
        row = self._row(plist.name, "ytmusic", str(plist.track_count or ""))
        self._bind_playlist_menu(row, plist)
        return row

    def _selected_playlist_id(self) -> str:
        row = self.playlist_list.get_selected_row()
        if row is None or row.get_index() >= len(self._playlists):
            return ""
        return self._playlists[row.get_index()].id

    def _reload_playlist_rows(self, *, select_id: str = "") -> None:
        keep = select_id or self._selected_playlist_id()
        self._clear(self.playlist_list)
        select = None
        for plist in self._playlists:
            row = self._playlist_row(plist)
            self.playlist_list.append(row)
            if plist.id == keep:
                select = row
        if select is not None:
            self.playlist_list.select_row(select)

    def _bind_playlist_menu(self, row: Gtk.ListBoxRow, plist) -> None:
        click = Gtk.GestureClick()
        click.set_button(Gdk.BUTTON_SECONDARY)
        click.connect("pressed", lambda g, *_a: self._show_playlist_menu(row, plist, g))
        row.add_controller(click)

    def _show_playlist_menu(self, row: Gtk.ListBoxRow, plist, gesture) -> None:
        self._dismiss_menu()
        pop = Gtk.Popover()
        pop.set_has_arrow(False)
        pop.add_css_class("ctx-menu")
        self._fill_playlist_menu(pop, row, plist)
        pop.set_parent(row)
        pop.popup()
        self._ctx_pop = pop
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)

    def _fill_playlist_menu(self, pop: Gtk.Popover, row: Gtk.ListBoxRow, plist) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)

        def run(fn) -> None:
            self._dismiss_menu()
            fn()

        for label in playlist_menu_actions(plist.id):
            if label == "Start mix":
                box.append(self._menu_button(label, lambda: run(lambda: self._start_playlist_mix(plist))))
            elif label == "Rename…":
                box.append(self._menu_button(label, lambda: self._fill_rename_playlist(pop, row, plist)))
            elif label == "Delete…":
                box.append(self._menu_button(label, lambda: self._fill_delete_playlist(pop, row, plist)))
        pop.set_child(box)

    def _fill_rename_playlist(self, pop: Gtk.Popover, row: Gtk.ListBoxRow, plist) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(10)
        box.set_margin_end(10)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.append(self._menu_button("← Back", lambda: self._fill_playlist_menu(pop, row, plist)))
        lab = Gtk.Label(label="Rename playlist", xalign=0)
        lab.add_css_class("meta")
        entry = Gtk.Entry()
        entry.set_text(plist.name)
        entry.set_placeholder_text("playlist name")
        save = Gtk.Button(label="Rename")
        save.add_css_class("flat")

        def rename_now(*_a) -> None:
            name = entry.get_text().strip()
            self._dismiss_menu()
            if not name or name == plist.name:
                return
            self._rename_playlist(plist, name)

        save.connect("clicked", rename_now)
        entry.connect("activate", rename_now)
        box.append(lab)
        box.append(entry)
        box.append(save)
        pop.set_child(box)
        entry.grab_focus()

    def _fill_delete_playlist(self, pop: Gtk.Popover, row: Gtk.ListBoxRow, plist) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(10)
        box.set_margin_end(10)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        warn = Gtk.Label(label=f"Delete “{plist.name}” from YouTube Music?", xalign=0)
        warn.add_css_class("meta")
        warn.set_wrap(True)
        box.append(warn)
        box.append(self._menu_button("Cancel", lambda: self._fill_playlist_menu(pop, row, plist)))
        box.append(self._menu_button("Delete", lambda: self._delete_playlist(plist)))
        pop.set_child(box)

    def _start_playlist_mix(self, plist) -> None:
        self.notebook.set_current_page(0)
        self._queue_cmd({"cmd": "playlist.mix", "id": plist.id}, timeout=40)

    def _rename_playlist(self, plist, name: str) -> None:
        self._async(
            f"renaming {plist.name}…",
            lambda: self.ipc.request({"cmd": "playlist.rename", "id": plist.id, "name": name}, timeout=20),
            lambda payload, err: self._got_playlist_rename(plist, name, payload, err),
        )

    def _got_playlist_rename(self, plist, name: str, payload, err) -> bool:
        if err:
            self._set_footer(err)
            self._show_notice(err)
            return False
        plist.name = name
        selected = self._selected_playlist_id()
        self._reload_playlist_rows(select_id=selected)
        if selected == plist.id:
            self.tracks_label.set_text(tracks_caption(playlist_name=name))
        self._show_notice(f"Renamed to {name}")
        return False

    def _delete_playlist(self, plist) -> None:
        self._dismiss_menu()
        self._async(
            f"deleting {plist.name}…",
            lambda: self.ipc.request({"cmd": "playlist.delete", "id": plist.id}, timeout=20),
            lambda payload, err: self._got_playlist_delete(plist, payload, err),
        )

    def _got_playlist_delete(self, plist, payload, err) -> bool:
        if err:
            self._set_footer(err)
            self._show_notice(err)
            return False
        was_selected = self._selected_playlist_id() == plist.id
        self._playlists = [row for row in self._playlists if row.id != plist.id]
        self._reload_playlist_rows()
        if was_selected:
            self.browse.lib_tracks = []
            self._render_tracks([])
            self.tracks_label.set_text(tracks_caption())
        self._show_notice(f"Deleted {plist.name}")
        return False

    def _on_playlist_selected(self, _l, row: Gtk.ListBoxRow | None) -> None:
        if row is None:
            return
        self._show_playlist(row.get_index())

    def _on_playlist_click(self, _g, _n, _x, y: float) -> None:
        if not self._is_searching():
            return
        row = self.playlist_list.get_row_at_y(int(y))
        if row is None:
            return
        selected = self.playlist_list.get_selected_row()
        if selected is None or selected.get_index() != row.get_index():
            return
        self._show_playlist(row.get_index())

    def _show_playlist(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._playlists):
            return
        if self.search_entry.get_text():
            self.search_entry.set_text("")
        plist = self._playlists[idx]
        gen = self.browse.open_playlist()
        self.tracks_label.set_text(tracks_caption(playlist_name=plist.name))
        self._render_tracks([])
        self._async(
            f"loading {plist.name}…",
            lambda: self.ipc.request({"cmd": "playlist.tracks", "id": plist.id}, timeout=40),
            lambda payload, err: self._got_playlist_tracks(gen, plist.id, payload, err),
        )

    def _got_playlist_tracks(self, gen: int, playlist_id: str, payload, err, *, append: bool = False) -> bool:
        if err:
            self._set_footer(err)
            return False
        tracks = parse_tracks(payload or {})
        if not self.browse.finish_playlist(gen, tracks, append=append):
            return False
        if append:
            start = len(self.browse.lib_tracks) - len(tracks) + 1
            self._append_track_rows(tracks, start)
        else:
            self._render_tracks(self.browse.visible())
        if page_done(payload):
            self._set_footer(f"{len(self.browse.lib_tracks)} tracks")
            return False
        self._set_footer(f"{len(self.browse.lib_tracks)} tracks…")
        self._async(
            "",
            lambda: self.ipc.request({"cmd": "playlist.tracks.more", "id": playlist_id}, timeout=40),
            lambda more, more_err: self._got_playlist_tracks(gen, playlist_id, more, more_err, append=True),
        )
        return False

    def _render_tracks(self, tracks) -> None:
        self._clear(self.track_list)
        self._append_track_rows(tracks, 1)

    def _append_track_rows(self, tracks, start: int) -> None:
        for i, track in enumerate(tracks, start=start):
            row = self._row(f"{i:02d}  {track.title}", track.artist, format_time(track.duration_secs))
            if not track.playable:
                row.add_css_class("unplayable")
            self._bind_song_menu(row, track, source="library")
            self.track_list.append(row)

    def _on_playlist_activated(self, _l, row: Gtk.ListBoxRow) -> None:
        idx = row.get_index()
        if idx >= len(self._playlists):
            return
        plist = self._playlists[idx]
        self.notebook.set_current_page(0)
        self._queue_cmd({"cmd": "playlist.play", "id": plist.id}, timeout=40)

    def _on_track_activated(self, _l, row: Gtk.ListBoxRow) -> None:
        tracks = self.browse.visible()
        idx = row.get_index()
        if idx >= len(tracks):
            return
        track = tracks[idx]
        if not track.playable:
            self._show_notice("Can't play here — YouTube-only")
            return
        self.notebook.set_current_page(0)
        self._queue_cmd({"cmd": "track.play", "track": track.to_ipc()}, timeout=40)

    def _on_search(self, *_a) -> None:
        if self.notebook.get_current_page() != 2:
            self.notebook.set_current_page(2)
        query = self.search_entry.get_text().strip()
        if not query:
            self.browse.search_tracks = None
            self.browse.generation += 1
            self._render_tracks(self.browse.visible())
            row = self.playlist_list.get_selected_row()
            name = ""
            if row is not None and 0 <= row.get_index() < len(self._playlists):
                name = self._playlists[row.get_index()].name
            self.tracks_label.set_text(tracks_caption(playlist_name=name))
            return
        gen = self.browse.begin_search()
        self.tracks_label.set_text(tracks_caption(query=query))
        self._async(
            f"searching {query}…",
            lambda: self.ipc.request({"cmd": "search", "query": query}, timeout=20),
            lambda payload, err: self._got_search(gen, query, payload, err),
        )

    def _got_search(self, gen: int, query: str, payload, err, *, append: bool = False) -> bool:
        if err:
            self._set_footer(err)
            return False
        tracks = parse_tracks(payload or {})
        if not self.browse.finish_search(gen, tracks, append=append):
            return False
        if append:
            start = len(self.browse.search_tracks or []) - len(tracks) + 1
            self._append_track_rows(tracks, start)
        else:
            self._render_tracks(self.browse.visible())
        total = len(self.browse.search_tracks or [])
        if page_done(payload):
            self._set_footer(f"{total} results · click a playlist to leave search")
            return False
        self._set_footer(f"{total} results…")
        self._async(
            "",
            lambda: self.ipc.request({"cmd": "search.more", "query": query}, timeout=20),
            lambda more, more_err: self._got_search(gen, query, more, more_err, append=True),
        )
        return False
