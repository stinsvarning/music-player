from __future__ import annotations

import time

import cairo
import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk

from music_player.spectrum import VIS_MODES, FieldState, normalize_vis
from music_player.theme import Palette, palette_named
from music_player.widgets.vis_paint import paint_field


class FieldView(Gtk.DrawingArea):
    """Music-reactive cell grid behind the deck. Redraws once per band poll."""

    def __init__(self) -> None:
        super().__init__()
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.mode = VIS_MODES[0]
        self.on_cycle = None
        self.state = FieldState()
        self._deck: Gtk.Widget | None = None
        self.palette: Palette = palette_named("mint")
        self.set_draw_func(self._draw)
        self.set_cursor_from_name("pointer")
        click = Gtk.GestureClick()
        click.connect("released", self._on_click)
        self.add_controller(click)

    @property
    def _bands(self) -> list[float]:
        return self.state.level

    @property
    def _amp(self) -> float:
        return self.state.amp

    def set_mode(self, mode: str) -> None:
        self.mode = normalize_vis(mode)
        self.queue_draw()

    def _on_click(self, *_a) -> None:
        if callable(self.on_cycle):
            self.on_cycle()

    def set_deck(self, deck: Gtk.Widget) -> None:
        self._deck = deck

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette
        self.queue_draw()

    def set_bands(self, bands: list[float]) -> None:
        self.state.set_bands(bands)
        self.queue_draw()

    def _deck_rect(self) -> tuple[float, float, float, float]:
        if self._deck is not None:
            ok, bounds = self._deck.compute_bounds(self)
            if ok:
                left, top = bounds.get_x(), bounds.get_y()
                return left, top, left + bounds.get_width(), top + bounds.get_height()
        return 0.0, 0.0, 0.0, 0.0

    def _draw(self, _area: Gtk.DrawingArea, cr: cairo.Context, width: int, height: int) -> None:
        paint_field(cr, width, height, self._deck_rect(), self.mode, self.palette, self.state, time.monotonic())
