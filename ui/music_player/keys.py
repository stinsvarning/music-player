"""Keyboard shortcuts and the help card."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, Gtk



HELP_LINES = (
    "space      play / pause",
    "n  p  s    next, previous, stop",
    "left right seek",
    "up down    volume",
    "l          like",
    "q  m       queue, library",
    "/          find",
    "delete     remove the selected queue row",
    "menu       open the context menu",
    "f11        fullscreen",
    "ctrl+q     quit",
    "?          close this card",
)


class KeysMixin:
    """PlayerWindow methods; state lives on the window (see PlayerWindow.__init__)."""

    def _bind_keys(self) -> None:
        ctrl = Gtk.EventControllerKey()
        ctrl.connect("key-pressed", self._on_key)
        self.add_controller(ctrl)

    def _on_key(self, _c, keyval, _code, state) -> bool:
        mods = state & Gtk.accelerator_get_default_mod_mask()
        if mods & Gdk.ModifierType.CONTROL_MASK and keyval in (Gdk.KEY_q, Gdk.KEY_Q):
            app = self.get_application()
            if app is not None and hasattr(app, "quit_engine"):
                app.quit_engine()
            return True
        if self.search_entry.has_focus():
            if keyval == Gdk.KEY_Escape:
                self.set_focus(None)
                return True
            return False
        if getattr(self, "_help_veil", None) is not None and self._help_veil.get_visible():
            if keyval in (Gdk.KEY_Escape, Gdk.KEY_question):
                self._help_veil.set_visible(False)
            return True
        if keyval == Gdk.KEY_question:
            self._toggle_help()
            return True
        if keyval == Gdk.KEY_Escape:
            self.set_focus(None)
            return True
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_KP_Delete):
            return self._delete_selected_queue_row()
        if keyval == Gdk.KEY_Menu or (
            keyval == Gdk.KEY_F10 and mods & Gdk.ModifierType.SHIFT_MASK
        ):
            self._open_context_menu()
            return True
        if keyval == Gdk.KEY_space:
            self._cmd("toggle")
            return True
        if keyval in (Gdk.KEY_n, Gdk.KEY_N):
            self._cmd("next")
            return True
        if keyval in (Gdk.KEY_p, Gdk.KEY_P):
            self._cmd("prev")
            return True
        if keyval in (Gdk.KEY_s, Gdk.KEY_S):
            self._cmd("stop")
            return True
        if keyval in (Gdk.KEY_l, Gdk.KEY_L):
            self.btn_like.set_active(not self.btn_like.get_active())
            return True
        if keyval == Gdk.KEY_Up:
            self.volume.set_value(min(100, self.volume.get_value() + 5))
            return True
        if keyval == Gdk.KEY_Down:
            self.volume.set_value(max(0, self.volume.get_value() - 5))
            return True
        if keyval in (Gdk.KEY_Left, Gdk.KEY_Right):
            delta = -5 if keyval == Gdk.KEY_Left else 5
            self._queue_cmd({"cmd": "seek", "value": max(0, self.status.position + delta)})
            return True
        if keyval == Gdk.KEY_F11:
            if self.is_fullscreen():
                self.unfullscreen()
            else:
                self.fullscreen()
            return True
        if keyval in (Gdk.KEY_m, Gdk.KEY_M):
            self._show_library()
            return True
        if keyval in (Gdk.KEY_q, Gdk.KEY_Q):
            self._show_queue()
            return True
        if keyval == Gdk.KEY_slash or (
            mods & Gdk.ModifierType.CONTROL_MASK and keyval in (Gdk.KEY_f, Gdk.KEY_F)
        ):
            self.search_entry.grab_focus()
            return True
        return False

    def _toggle_help(self) -> None:
        veil = getattr(self, "_help_veil", None)
        if veil is None:
            return
        veil.set_visible(not veil.get_visible())

    def _help_overlay(self) -> Gtk.Widget:
        veil = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True)
        veil.add_css_class("login-veil")
        veil.set_visible(False)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        card.add_css_class("login-card")
        card.set_halign(Gtk.Align.CENTER)
        card.set_valign(Gtk.Align.CENTER)
        title = Gtk.Label(label="Keys", xalign=0)
        title.add_css_class("title")
        card.append(title)
        for line in HELP_LINES:
            lab = Gtk.Label(label=line, xalign=0)
            lab.add_css_class("hint")
            card.append(lab)
        veil.append(card)
        click = Gtk.GestureClick()
        click.connect("pressed", lambda *_a: veil.set_visible(False))
        veil.add_controller(click)
        self._help_veil = veil
        return veil
