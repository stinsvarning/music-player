"""Palette, theme and config watching, and the visualizer."""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gio, GLib

from .prefs import config_path, load_vis_mode, save_vis_mode
from .spectrum import cycle_vis
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
        self._config_reload_id = 0
        mode = load_vis_mode()
        if mode != getattr(self.spectrum, "mode", None):
            self._apply_vis(mode)
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
        if getattr(self, "spectrum", None) is not None:
            self.spectrum.set_mode(mode)
            self.spectrum.on_cycle = self._cycle_vis
        if getattr(self, "field", None) is not None:
            self.field.set_mode(mode)
            self.field.on_cycle = self._cycle_vis

    def _cycle_vis(self) -> None:
        mode = cycle_vis(getattr(self.spectrum, "mode", "bricks"))
        self._apply_vis(mode)
        save_vis_mode(mode)

    def _on_bands(self, raw: dict | None) -> bool:
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
