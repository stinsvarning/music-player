"""The queue list: rendering, the current row, the song menu, saving the queue and drag to reorder."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, GLib, Gtk

from .models import (
    PlaylistInfo,
    Track,
    default_queue_playlist_name,
    format_time,
    moved_index,
    play_next_target,
    queue_needs_rebuild,
    song_menu_actions,
)


class QueueViewMixin:
    """PlayerWindow methods; state lives on the window (see PlayerWindow.__init__)."""

    def _on_queue_activate(self, _l, row: Gtk.ListBoxRow) -> None:
        idx = row.get_index()
        if 0 <= idx < len(self._queue) and not self._queue[idx].playable:
            self._show_notice("Can't play here — YouTube-only")
            return
        self._queue_cmd({"cmd": "queue.play", "index": idx})

    def _render_queue(self, tracks: list[Track], index: int, *, select_index: int | None = None) -> None:
        old_ids = list(self._row_ids)
        new_ids = [t.id for t in tracks]
        self._queue = list(tracks)
        self.queue_empty.set_visible(not tracks)
        if not queue_needs_rebuild(old_ids, new_ids) and self.queue_list.get_first_child() is not None:
            self._mark_current_row(index)
            if select_index is not None:
                self._select_queue_row(select_index, focus=False)
            return
        selected = self.queue_list.get_selected_row()
        sel_idx = selected.get_index() if selected is not None else None
        if select_index is not None:
            sel_idx = select_index
        had_focus = self._queue_has_focus()
        self._row_ids = new_ids
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
                self._select_queue_row(sel_idx, focus=had_focus)
            return False

        if sel_idx is not None:
            self._select_queue_row(sel_idx, focus=had_focus)
        GLib.idle_add(restore)

    def _queue_has_focus(self) -> bool:
        focus = self.get_focus()
        while focus is not None:
            if focus is self.queue_list:
                return True
            focus = focus.get_parent()
        return False

    def _select_queue_row(self, index: int, *, focus: bool) -> None:
        row = self.queue_list.get_row_at_index(index)
        if row is None:
            return
        self.queue_list.select_row(row)
        if focus:
            row.grab_focus()

    def _move_queue_row(self, src: int, dest: int) -> bool:
        """Move one queue row (engine + an optimistic local re-render); the
        selection follows the moved row."""
        total = len(self._queue)
        if not (0 <= src < total) or not (0 <= dest < total) or src == dest:
            return False
        self._queue_cmd({"cmd": "queue.move", "from": src, "to": dest})
        tracks = list(self._queue)
        item = tracks.pop(src)
        tracks.insert(dest, item)
        current = moved_index(self.status.index, src, dest) if self.status.index >= 0 else -1
        self.status.index = current
        self._render_queue(tracks, current, select_index=dest)
        return True

    def _move_selected_queue_row(self, delta: int) -> bool:
        if self.body_stack.get_visible_child_name() != "queue":
            return False
        row = self.queue_list.get_selected_row()
        if row is None:
            return False
        src = row.get_index()
        dest = max(0, min(len(self._queue) - 1, src + delta))
        self._move_queue_row(src, dest)
        return True

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

        idx = row.get_index() if source == "queue" else -1
        current = self.status.index if source == "queue" else -1
        for label in song_menu_actions(source, row=idx, current=current, total=len(self._queue)):
            if label == "Play next" and source == "queue":
                box.append(self._menu_button(label, lambda: run(lambda: self._move_queue_row(row.get_index(), play_next_target(row.get_index(), self.status.index)))))
            elif label == "Move to top":
                box.append(self._menu_button(label, lambda: run(lambda: self._move_queue_row(row.get_index(), 0))))
            elif label == "Move to bottom":
                box.append(self._menu_button(label, lambda: run(lambda: self._move_queue_row(row.get_index(), len(self._queue) - 1))))
            elif label == "Start mix":
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
        self._move_queue_row(src, dest)
        return True
