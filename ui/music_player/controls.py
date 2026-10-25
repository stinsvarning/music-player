"""Transport controls: seek, volume, shuffle, repeat, autoplay, like and the sleep timer."""

from __future__ import annotations

import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import GLib, Gtk

from .models import clamp_seek_target, format_time


class ControlsMixin:
    """PlayerWindow methods; state lives on the window (see PlayerWindow.__init__)."""

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
        target = clamp_seek_target(target, self.status.duration)
        self._queue_cmd({"cmd": "seek", "value": target})
        return False

    def _on_volume(self, scale: Gtk.Scale) -> None:
        if self._syncing:
            return
        self.vol_num.set_text(str(int(scale.get_value())))
        self._set_vis_volume(scale.get_value())
        self._queue_cmd({"cmd": "volume", "value": scale.get_value()})

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
