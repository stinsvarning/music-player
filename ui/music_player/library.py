from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk

from .models import can_autoselect_playlist, format_time, page_done, parse_playlists, parse_tracks, tracks_caption


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
            self.playlist_list.append(self._row(plist.name, "ytmusic", str(plist.track_count or "")))
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
