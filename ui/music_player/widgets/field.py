from __future__ import annotations

import math
import time

import cairo
import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk

from music_player.spectrum import FIELD_COLS, field_band_at, field_clearance
from music_player.theme import Palette, mix_hex, palette_named

BAYER = (
    0, 32, 8, 40, 2, 34, 10, 42,
    48, 16, 56, 24, 50, 18, 58, 26,
    12, 44, 4, 36, 14, 46, 6, 38,
    60, 28, 52, 20, 62, 30, 54, 22,
    3, 35, 11, 43, 1, 33, 9, 41,
    51, 19, 59, 27, 49, 17, 57, 25,
    15, 47, 7, 39, 13, 45, 5, 37,
    63, 31, 55, 23, 61, 29, 53, 21,
)


def _lcg(n: int) -> tuple[float, ...]:
    x = 1234567
    out: list[float] = []
    for _ in range(n):
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        out.append(x / 0x7FFFFFFF)
    return tuple(out)


JITTER = _lcg(4096)


class FieldView(Gtk.DrawingArea):
    def __init__(self) -> None:
        super().__init__()
        self.set_hexpand(True)
        self.set_vexpand(True)
        self._bands = [0.0] * 10
        self._amp = 0.0
        self._deck: Gtk.Widget | None = None
        self.palette: Palette = palette_named("mint")
        self.set_draw_func(self._draw)

    def set_deck(self, deck: Gtk.Widget) -> None:
        self._deck = deck

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette
        self.queue_draw()

    def set_bands(self, bands: list[float]) -> None:
        vals = [max(0.0, min(1.0, float(x))) for x in (bands or [])[:10]]
        while len(vals) < 10:
            vals.append(0.0)
        mean = sum(vals) / 10.0
        self._amp = self._amp * 0.9 + mean * 0.1
        self._bands = vals
        self.queue_draw()

    def _hex(self, value: str) -> tuple[float, float, float]:
        v = value.lstrip("#")
        if len(v) == 3:
            v = "".join(ch * 2 for ch in v)
        return int(v[0:2], 16) / 255.0, int(v[2:4], 16) / 255.0, int(v[4:6], 16) / 255.0

    def _draw(self, _area: Gtk.DrawingArea, cr: cairo.Context, width: int, height: int) -> None:
        cr.set_source_rgb(*self._hex(self.palette.bg))
        cr.rectangle(0, 0, width, height)
        cr.fill()
        if width < 8 or height < 8:
            return
        cell = max(4.0, width / FIELD_COLS)
        deck_l, deck_t, deck_r, deck_b = 0.0, 0.0, 0.0, 0.0
        if self._deck is not None:
            ok, bounds = self._deck.compute_bounds(self)
            if ok:
                deck_l, deck_t = bounds.get_x(), bounds.get_y()
                deck_r = deck_l + bounds.get_width()
                deck_b = deck_t + bounds.get_height()
        mid_x = (deck_l + deck_r) / 2 if deck_r > deck_l else width / 2
        half = max(1.0, width / 2)
        dim = self._hex(mix_hex(self.palette.bg, self.palette.accent, 0.28))
        mid = self._hex(mix_hex(self.palette.bg, self.palette.accent, 0.55))
        lit = self._hex(self.palette.accent)
        t = time.monotonic()
        cols = int(math.ceil(width / cell)) + 2
        rows = int(math.ceil(height / cell)) + 2
        for col in range(-1, cols):
            x = col * cell
            cx = x + cell / 2
            level = field_band_at(cx, mid_x, half, self._bands)
            tall = level * (height / cell) * 0.92
            dx = max(deck_l - cx, 0.0, cx - deck_r) if deck_r > deck_l else 0.0
            for row in range(-1, rows):
                y = row * cell
                cy = y + cell / 2
                dy = max(deck_t - cy, 0.0, cy - deck_b) if deck_b > deck_t else 0.0
                shade = field_clearance(dx, dy)
                if shade < 0.004:
                    continue
                j = JITTER[(row * 37 + col * 11) & 4095]
                tw = 0.5 + 0.5 * math.sin(t * 1.1 + j * 6.283)
                base = 0.55 + 0.45 * JITTER[((row & 63) * 64 + (col & 63)) & 4095]
                energy = shade * (0.30 + 0.52 * base * base + 0.18 * tw + self._amp * 0.22) * 0.34
                spec = 0.0
                if level > 0:
                    up = (height - cy) / cell
                    if 0 <= up < tall:
                        spec = level * (1 - up / tall) ** 0.85
                        energy += spec * 0.72 * min(1.0, shade * 3)
                threshold = 0.78 * ((BAYER[(row & 7) * 8 + (col & 7)] + 0.5) / 64) + 0.22 * j
                if energy <= threshold:
                    continue
                heat = spec * 0.55 + self._amp * 0.12
                color = lit if heat > 0.34 else mid if heat > 0.1 else dim
                cr.set_source_rgb(*color)
                cr.rectangle(round(x), round(y), max(1, round(cell) - 1), max(1, round(cell) - 1))
                cr.fill()
