"""The footer status line, notices and the lyrics pane."""

from __future__ import annotations

import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import GLib, Gtk

from .models import footer_kind, is_login_error, lyric_lines, playback_word


UNDO_NOTE_SECONDS = 6.0
UNDO_FADE_MS = 600


class FooterMixin:
    """PlayerWindow methods; state lives on the window (see PlayerWindow.__init__)."""

    def _show_undo_note(self, label: str) -> None:
        """Quiet "<label> · Undo" at the right of the footer; fades after a few seconds."""
        self._stop_undo_timers()
        self.undo_label.set_text(f"{label} ·")
        self.undo_note.set_opacity(1.0)
        self.undo_note.set_visible(True)
        self._undo_hold = GLib.timeout_add(int(UNDO_NOTE_SECONDS * 1000), self._fade_undo_note)

    def _fade_undo_note(self) -> bool:
        self._undo_hold = 0
        start = time.monotonic()

        def step() -> bool:
            left = 1.0 - (time.monotonic() - start) * 1000 / UNDO_FADE_MS
            if left <= 0:
                self._undo_fade = 0
                self._hide_undo_note()
                return False
            self.undo_note.set_opacity(left)
            return True

        self._undo_fade = GLib.timeout_add(40, step)
        return False

    def _hide_undo_note(self) -> None:
        self._stop_undo_timers()
        self.undo_note.set_visible(False)
        self.undo_note.set_opacity(1.0)

    def _stop_undo_timers(self) -> None:
        for name in ("_undo_hold", "_undo_fade"):
            src = getattr(self, name, 0)
            if src:
                GLib.source_remove(src)
            setattr(self, name, 0)

    def _undo(self) -> None:
        self._hide_undo_note()
        self._queue_cmd({"cmd": "queue.undo"})

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
