from __future__ import annotations

import threading

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gio, GLib, Gtk

from .models import login_status_text

YTM_URL = "https://music.youtube.com"


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
        self.login_browser_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.login_open_btn = Gtk.Button(label="Sign in")
        self.login_open_btn.connect("clicked", lambda *_: self._open_youtube_login())
        done_btn = Gtk.Button(label="Check again")
        done_btn.add_css_class("flat")
        done_btn.connect("clicked", lambda *_: self._refresh_login())
        card.append(title)
        card.append(body)
        card.append(self.login_status)
        card.append(self.login_browser_box)
        card.append(self.login_open_btn)
        card.append(done_btn)
        veil.append(card)
        self.login_veil = veil
        veil.set_visible(False)
        return veil

    def _fill_login_browsers(self, browsers: list | None) -> None:
        box = getattr(self, "login_browser_box", None)
        if box is None:
            return
        child = box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            box.remove(child)
            child = nxt
        rows = list(browsers or [])
        for browser in rows:
            label = browser.get("label") or "browser"
            btn = Gtk.Button(label=f"Sign in with {label}")
            btn.connect("clicked", lambda _b, spec=browser: self._open_youtube_login(spec))
            box.append(btn)
        if getattr(self, "login_open_btn", None) is not None:
            self.login_open_btn.set_visible(not rows)

    def _open_youtube_login(self, browser: dict | None = None) -> None:
        spec = (browser or {}).get("spec") or ""
        name = (browser or {}).get("label") or "the browser"
        self._login_spec = spec
        self.login_status.set_text(f"Sign in with {name}. This window will pick it up…")
        try:
            self._launch_youtube(browser or {})
        except Exception as exc:  # noqa: BLE001
            self.login_status.set_text(str(exc))
            return
        self._start_login_watch()

    def _launch_youtube(self, browser: dict) -> None:
        for desk in browser.get("desktop") or []:
            name = desk if str(desk).endswith(".desktop") else f"{desk}.desktop"
            try:
                info = Gio.DesktopAppInfo.new(name)
            except Exception:
                info = None
            if info is not None:
                info.launch_uris([YTM_URL], None)
                return
        for bin_name in browser.get("bins") or []:
            try:
                info = Gio.AppInfo.create_from_commandline(
                    str(bin_name),
                    None,
                    Gio.AppInfoCreateFlags.SUPPORTS_URIS,
                )
            except Exception:
                continue
            if info is not None:
                info.launch_uris([YTM_URL], None)
                return
        Gio.AppInfo.launch_default_for_uri(YTM_URL, None)

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

    def _refresh_login(self, cookies_from: str | None = None) -> None:
        if self._login_busy:
            return
        self._login_busy = True
        spec = cookies_from if cookies_from is not None else getattr(self, "_login_spec", "")
        self.login_status.set_text("Looking for a YouTube Music session…")

        def work() -> None:
            try:
                payload = {"cmd": "auth.refresh", "skip_saved": True, "force": True}
                if spec:
                    payload["cookies_from"] = spec
                result = self.ipc.request(payload, timeout=25)
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
        self._fill_login_browsers((payload or {}).get("browsers"))
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
