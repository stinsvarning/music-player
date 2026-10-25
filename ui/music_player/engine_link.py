"""Talking to the engine: status push and fallback poll, command lanes, and applying status to the widgets."""

from __future__ import annotations

import queue
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import GLib, Gtk

from .ipc import EngineError, lane_for
from .models import (
    format_time,
    interpolate_position,
    parse_status,
    pump_intervals,
    parse_tracks,
    should_apply_engine_rating,
    UNDO_NOTES,
)


class EngineLinkMixin:
    """PlayerWindow methods; state lives on the window (see PlayerWindow.__init__)."""

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

    def _pump(self) -> None:
        """The meter, plus a status poll that is only a fallback once subscribed.

        Slow commands run on their own lanes; status changes arrive pushed on the
        subscribe stream (see _subscribe_loop).
        """
        last = 0.0
        last_bands = 0.0
        while not self._pump_stop.is_set():
            now = time.monotonic()
            # Visualizer off: no band polls at all (the engine stops sampling too).
            if not getattr(self, "_bands_wanted", True):
                last_bands = now
            elif now - last_bands >= pump_intervals(self._playing_hint, self._subscribed)[0]:
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
                err = resp.get("error") or "engine error"
                if payload.get("cmd") == "queue.undo" and "nothing to undo" in err:
                    err = "nothing to undo"
                GLib.idle_add(self._set_footer, err)
            elif payload.get("cmd") == "playlist.add":
                GLib.idle_add(self._set_footer, "saved to playlist")
            elif payload.get("cmd") in {
                "track.play_next",
                "track.queue",
                "queue.move",
                "queue.remove",
                "track.mix",
                "playlist.mix",
                "queue.clear_upcoming",
                "queue.undo",
            }:
                GLib.idle_add(self._refresh_queue)
                GLib.idle_add(self._after_queue_edit, payload.get("cmd"), resp)
        except (OSError, EngineError) as exc:
            GLib.idle_add(self._note_link_down, str(exc))

    def _after_queue_edit(self, cmd: str, resp: dict) -> bool:
        if cmd == "queue.undo":
            self._hide_undo_note()
            self._set_footer("undone")
        elif cmd == "queue.clear_upcoming" and not int(resp.get("removed") or 0):
            self._set_footer("nothing after this track")
        elif cmd in UNDO_NOTES:
            self._show_undo_note(UNDO_NOTES[cmd])
        return False

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
        self._sync_vis(raw)
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
