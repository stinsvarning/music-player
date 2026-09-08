from __future__ import annotations

import cairo
import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk

from music_player.spectrum import (
    BRICK_COLS,
    BRICK_SEGS,
    bar_index_at,
    brick_columns,
    tick_brick_peaks,
)
from music_player.theme import Palette, mix_hex, palette_named


class SpectrumView(Gtk.DrawingArea):
    def __init__(self) -> None:
        super().__init__()
        self.set_hexpand(True)
        self.set_content_height(84)
        self._cols = [0] * BRICK_COLS
        self._peaks = [0] * BRICK_COLS
        self._hover = -1
        self.palette: Palette = palette_named("mint")
        self.set_draw_func(self._draw)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", lambda *_a: self._set_hover(-1))
        self.add_controller(motion)

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette
        self.queue_draw()

    def set_bands(self, bands: list[float]) -> None:
        self._cols = brick_columns(bands)
        self._peaks = tick_brick_peaks(self._peaks, self._cols)
        self.queue_draw()

    def _on_motion(self, _c, x, _y) -> None:
        self._set_hover(bar_index_at(x, self.get_width(), len(self._cols)))

    def _set_hover(self, idx: int) -> None:
        if idx == self._hover:
            return
        self._hover = idx
        self.queue_draw()

    def _hex(self, value: str) -> tuple[float, float, float]:
        v = value.lstrip("#")
        if len(v) == 3:
            v = "".join(ch * 2 for ch in v)
        return int(v[0:2], 16) / 255.0, int(v[2:4], 16) / 255.0, int(v[4:6], 16) / 255.0

    def _draw(self, _area: Gtk.DrawingArea, cr: cairo.Context, width: int, height: int) -> None:
        lcd = mix_hex(self.palette.bg, "#000000", 0.45)
        cr.set_source_rgb(*self._hex(lcd))
        cr.rectangle(0, 0, width, height)
        cr.fill()
        n = len(self._cols)
        if n == 0 or width <= 0 or height <= 0:
            return
        gap = 1.5
        col_w = max(2.0, (width - gap * (n + 1)) / n)
        seg = max(3.5, (height - 4) / BRICK_SEGS)
        brick = max(2.0, seg - 1.6)
        low = self._hex(mix_hex(self.palette.bg, self.palette.accent, 0.45))
        mid = self._hex(self.palette.accent)
        high = self._hex(self.palette.peak)
        for i, lit in enumerate(self._cols):
            x = gap + i * (col_w + gap)
            hot = i == self._hover
            peak = self._peaks[i] if i < len(self._peaks) else lit
            for s in range(BRICK_SEGS):
                y = height - 2 - (s + 1) * seg
                on = s < lit or s + 1 == peak
                if not on:
                    cr.set_source_rgba(*mid, 0.08)
                elif s >= 10:
                    cr.set_source_rgb(*(high if not hot else tuple(min(1.0, c * 1.2) for c in high)))
                elif s >= 6:
                    cr.set_source_rgb(*(mid if not hot else tuple(min(1.0, c * 1.15) for c in mid)))
                else:
                    cr.set_source_rgb(*low)
                cr.rectangle(x, y + (seg - brick), col_w, brick)
                cr.fill()
