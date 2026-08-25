from __future__ import annotations

import threading

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gio, GLib, Gtk

from .models import login_status_text


class LoginMixin:
    def _login_overlay(self) -> Gtk.Widget:
        veil = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True)
        veil.add_css_class("login-veil")
        veil.set_valign(Gtk.Align.FILL)
        veil.set_halign(Gtk.Align.FILL)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.add_css_class("login-card")
        card.set_hexpand(True)
        card.set_vexpand(True)
        card.set_halign(Gtk.Align.CENTER)
        card.set_valign(Gtk.Align.CENTER)
        title = Gtk.Label(label="Sign in with Google")
        title.add_css_class("title")
        title.set_wrap(True)
        body = Gtk.Label(
            label="Uses the YouTube Music session from a browser on this computer. "
            "Premium quality follows that account."
        )
        body.add_css_class("meta")
        body.set_wrap(True)
        body.set_max_width_chars(44)
        self.login_status = Gtk.Label(label="")
        self.login_status.add_css_class("hint")
        self.login_status.set_wrap(True)
        open_btn = Gtk.Button(label="Sign in")
        open_btn.connect("clicked", self._open_youtube_login)
        done_btn = Gtk.Button(label="Check again")
        done_btn.add_css_class("flat")
        done_btn.connect("clicked", lambda *_: self._refresh_login())
        card.append(title)
        card.append(body)
        card.append(self.login_status)
        card.append(open_btn)
        card.append(done_btn)
        veil.append(card)
        self.login_veil = veil
        veil.set_visible(False)
        return veil

    def _open_youtube_login(self, *_a) -> None:
        self.login_status.set_text("Sign in in the browser. This window will pick it up…")
        try:
            Gio.AppInfo.launch_default_for_uri("https://music.youtube.com", None)
        except Exception as exc:  # noqa: BLE001
            self.login_status.set_text(str(exc))
            return
        self._start_login_watch()

    def _start_login_watch(self) -> None:
        if self._login_timer:
            return
        self._login_timer = GLib.timeout_add(5000, self._on_login_tick)

    def _stop_login_watch(self) -> None:
        if self._login_timer:
            GLib.source_remove(self._login_timer)
            self._login_timer = 0

    def _on_login_tick(self) -> bool:
        if not self.login_veil.get_visible():
            self._login_timer = 0
            return False
        self._refresh_login()
        return True

    def _refresh_login(self) -> None:
        if self._login_busy:
            return
        self._login_busy = True
        self.login_status.set_text("Looking for a YouTube Music session…")

        def work() -> None:
            try:
                result = self.ipc.request(
                    {"cmd": "auth.refresh", "skip_saved": True, "force": True},
                    timeout=25,
                )
                err = None
            except Exception as exc:  # noqa: BLE001
                result = None
                err = str(exc)
            GLib.idle_add(self._got_login, result, err)

        threading.Thread(target=work, daemon=True).start()

    def _got_login(self, payload, err) -> bool:
        self._login_busy = False
        if err:
            self.login_status.set_text(err)
            return False
        if payload and payload.get("logged_in"):
            self._hide_login()
            self._load_playlists()
            return False
        self.login_status.set_text(login_status_text(payload))
        return False

    def _show_login(self, message: str = "", *, watch: bool = False) -> None:
        self.login_veil.set_visible(True)
        if message:
            self.login_status.set_text(message)
        if watch:
            self._start_login_watch()

    def _hide_login(self) -> None:
        self._stop_login_watch()
        self.login_veil.set_visible(False)
        self.login_status.set_text("")
