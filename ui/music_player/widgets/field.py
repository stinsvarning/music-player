from __future__ import annotations

import time

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Graphene", "1.0")

from gi.repository import Gdk, GLib, Graphene, Gtk

from music_player.spectrum import VIS_MODES, FieldState, normalize_vis
from music_player.theme import Palette, palette_named
from music_player.widgets.vis_paint import (
    field_cells,
    field_geom,
    field_grid_draw,
    field_tones,
    paint_field,
    render_layer,
    rgb,
)


def _texture(surf: cairo.ImageSurface) -> Gdk.Texture:
    """An opaque Cairo RGB24 surface as a GPU texture (no conversion: BGRX in memory)."""
    data = GLib.Bytes.new(bytes(surf.get_data()))
    return Gdk.MemoryTexture.new(surf.get_width(), surf.get_height(), Gdk.MemoryFormat.B8G8R8X8, data, surf.get_stride())


def _rgba(color: tuple[float, float, float]) -> Gdk.RGBA:
    out = Gdk.RGBA()
    out.red, out.green, out.blue, out.alpha = color[0], color[1], color[2], 1.0
    return out


class FieldView(Gtk.DrawingArea):
    """Music-reactive cell grid behind the deck. Redraws once per band poll, and
    not at all while it stays dark.

    Drawn with GtkSnapshot rather than Cairo: the static grid is one cached
    texture and each lit cell a solid rectangle, so a redraw no longer rasterises
    and uploads a full-window image. The pixels are the same as paint_field's.
    Still a DrawingArea for its "resize" signal (the deck sizes itself from it).
    """

    def __init__(self) -> None:
        super().__init__()
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.mode = VIS_MODES[0]
        self.on_cycle = None
        self.state = FieldState()
        self._deck: Gtk.Widget | None = None
        self.palette: Palette = palette_named("mint")
        self._grid: tuple | None = None  # (key, texture)
        self._dark_drawn = False  # the last frame drawn had no lit cells
        self.draws = 0  # snapshots taken; for tests and frame counting
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
        self._dark_drawn = False
        self.queue_draw()

    def _on_click(self, *_a) -> None:
        if callable(self.on_cycle):
            self.on_cycle()

    def set_deck(self, deck: Gtk.Widget) -> None:
        self._deck = deck

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette
        self._dark_drawn = False
        self.queue_draw()

    def set_volume(self, volume: float | None) -> None:
        self.state.set_volume(volume)

    def set_bands(self, bands: list[float]) -> None:
        self.state.set_bands(bands)
        # Silence (paused, stopped, a quiet intro) leaves the field dark: once a
        # dark frame is on screen there is nothing to redraw until music returns.
        if self._dark_drawn and self._is_dark():
            return
        self.queue_draw()

    def _is_dark(self) -> bool:
        if any(self.state.bands_for(self.mode)):
            return False
        return self.mode != "waterfall" or not any(any(frame) for frame in self.state.history)

    def _deck_rect(self) -> tuple[float, float, float, float]:
        if self._deck is not None:
            ok, bounds = self._deck.compute_bounds(self)
            if ok:
                left, top = bounds.get_x(), bounds.get_y()
                return left, top, left + bounds.get_width(), top + bounds.get_height()
        return 0.0, 0.0, 0.0, 0.0

    def _grid_texture(self, geom, width: int, height: int, scale: int) -> Gdk.Texture:
        key, draw = field_grid_draw(geom, self.palette)
        full = key + (width, height, scale)
        if self._grid is None or self._grid[0] != full:
            self._grid = (full, _texture(render_layer(width, height, scale, scale, draw)))
        return self._grid[1]

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        self.draws += 1
        width, height = self.get_width(), self.get_height()
        if width < 8 or height < 8:
            if width > 0 and height > 0:
                snapshot.append_color(_rgba(rgb(self.palette.bg)), Graphene.Rect().init(0, 0, width, height))
            return
        geom = field_geom(width, height, self._deck_rect())
        cells = field_cells(geom, height, self.mode, self.state, time.monotonic())
        self._dark_drawn = not any(cells)
        snapshot.append_texture(self._grid_texture(geom, width, height, self.get_scale_factor()), Graphene.Rect().init(0, 0, width, height))
        for color, rects in zip(field_tones(self.palette), cells):
            if not rects:
                continue
            rgba = _rgba(color)
            for x, y, w, h in rects:
                snapshot.append_color(rgba, Graphene.Rect().init(x, y, w, h))

    def paint(self, cr: cairo.Context, width: int, height: int) -> None:
        """The same picture through Cairo (previews and tests)."""
        paint_field(cr, width, height, self._deck_rect(), self.mode, self.palette, self.state, time.monotonic())
