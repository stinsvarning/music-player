"""Palette, theme and config watching, and the visualizer."""

from __future__ import annotations

import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gio, GLib

from .prefs import config_path, config_vis_mode
from .spectrum import VIS_OFF, cycle_vis, vis_name
from .theme import (
    Palette,
    css_for,
    load_active_palette,
    omarchy_colors_paths,
    omarchy_current_dir,
    omarchy_state_dir,
)


class AppearanceMixin:
    """PlayerWindow methods; state lives on the window (see PlayerWindow.__init__)."""

    def _apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._css.load_from_data(css_for(palette).encode())
        self.spectrum.set_palette(palette)
        if getattr(self, "field", None) is not None:
            self.field.set_palette(palette)

    def _paint(self) -> None:
        self._apply_palette(self._base_palette)

    def _watch_theme(self) -> None:
        seen: set[str] = set()
        watch = [
            *omarchy_colors_paths(),
            omarchy_state_dir(),
            omarchy_state_dir() / "theme",
            omarchy_state_dir() / "theme.name",
            omarchy_current_dir(),
            omarchy_current_dir() / "theme",
            Path.home() / ".config/omarchy/current",
            Path.home() / ".config/omarchy/current/theme",
        ]
        for path in watch:
            key = str(path)
            if key in seen or not path.exists():
                continue
            seen.add(key)
            monitor = Gio.File.new_for_path(key).monitor(Gio.FileMonitorFlags.WATCH_MOVES, None)
            monitor.connect("changed", self._on_theme_changed)
            self._theme_monitors.append(monitor)
        self._watch_config()

    def _watch_config(self) -> None:
        """Pick up a hand-edited vis_mode in config.toml without a restart."""
        self._config_reload_id = 0
        try:
            folder = config_path().parent
            if not folder.exists():
                return
            monitor = Gio.File.new_for_path(str(folder)).monitor(Gio.FileMonitorFlags.WATCH_MOVES, None)
        except GLib.Error:
            return
        monitor.connect("changed", self._on_config_changed)
        self._theme_monitors.append(monitor)

    def _on_config_changed(self, _monitor, file, other, _event) -> None:
        name = config_path().name
        if (file is None or file.get_basename() != name) and (other is None or other.get_basename() != name):
            return
        if self._config_reload_id:
            GLib.source_remove(self._config_reload_id)
        self._config_reload_id = GLib.timeout_add(150, self._reload_config)

    def _reload_config(self) -> bool:
        """A changed vis_mode line applies live and becomes the saved choice; edits
        to other keys leave the current (possibly clicked) look alone."""
        self._config_reload_id = 0
        mode = config_vis_mode()
        if mode is None or mode == getattr(self, "_config_vis", None):
            return False
        self._config_vis = mode
        if mode != getattr(self.spectrum, "mode", None):
            self._choose_vis(mode)
        return False

    def _on_theme_changed(self, *_a) -> None:
        if self._theme_reload_id:
            GLib.source_remove(self._theme_reload_id)
        self._theme_reload_id = GLib.timeout_add(150, self._reload_theme)

    def _reload_theme(self) -> bool:
        self._theme_reload_id = 0
        try:
            self._base_palette = load_active_palette()
            self._paint()
        except (OSError, ValueError):
            pass
        return False

    def _apply_vis(self, mode: str) -> None:
        self._bands_wanted = mode != VIS_OFF  # read by the pump thread
        if getattr(self, "spectrum", None) is not None:
            self.spectrum.set_mode(mode)
            self.spectrum.on_cycle = self._cycle_vis
        if getattr(self, "field", None) is not None:
            self.field.set_mode(mode)
            self.field.on_cycle = self._cycle_vis

    def _cycle_vis(self) -> None:
        self._choose_vis(cycle_vis(getattr(self.spectrum, "mode", "bricks")))

    def _choose_vis(self, mode: str) -> None:
        """Show a look and have the engine remember it (and stop or start its band
        analysis for off). The engine keeps it in session.json, not config.toml."""
        self._apply_vis(mode)
        self._engine_vis = mode
        self._vis_chosen_at = time.monotonic()
        self._queue_cmd({"cmd": "vis", "mode": mode})

    def _sync_vis(self, raw: dict) -> None:
        """Follow a look chosen elsewhere (another window, music-player-ctl vis), and
        make sure the engine's analysis matches this window (e.g. off from config
        on a first run, before anything was saved)."""
        if "vis_on" not in raw:
            return  # older engine
        if time.monotonic() - getattr(self, "_vis_chosen_at", -10.0) < 2.0:
            return  # our own click is still on its way; statuses may predate it
        saved = vis_name(raw.get("vis_mode"))
        if saved and saved != getattr(self, "_engine_vis", None):
            self._engine_vis = saved
            if saved != getattr(self.spectrum, "mode", None):
                self._apply_vis(saved)
        mode = getattr(self.spectrum, "mode", "bricks")
        want = mode != VIS_OFF
        if bool(raw.get("vis_on")) != want:
            if getattr(self, "_vis_sync_sent", None) != mode:
                self._vis_sync_sent = mode
                self._queue_cmd({"cmd": "vis", "mode": mode, "save": False})
        else:
            self._vis_sync_sent = None

    def _on_bands(self, raw: dict | None) -> bool:
        if not getattr(self, "_bands_wanted", True):
            return False
        bands = [float(x) for x in (raw.get("bands") or [])] if raw and raw.get("ok") else []
        if self.status.state != "playing":
            bands = [0.0] * 10
        self.spectrum.set_bands(bands)
        if getattr(self, "field", None) is not None:
            self.field.set_bands(bands)
        return False

    def _set_vis_volume(self, volume: float) -> None:
        """The visualizers calm down and dim with the volume slider."""
        self.spectrum.set_volume(volume)
        if getattr(self, "field", None) is not None:
            self.field.set_volume(volume)
