from __future__ import annotations

import cairo
import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk

from music_player.spectrum import interpolate_bars, tick_peaks
from music_player.theme import Palette, palette_named


class SpectrumView(Gtk.DrawingArea):
    def __init__(self) -> None:
        super().__init__()
        self.set_hexpand(True)
        self.set_content_height(44)
        self._bars = [0.0] * 36
        self._peaks = [0.0] * 36
        self.palette: Palette = palette_named("mint")
        self.set_draw_func(self._draw)

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette
        self.queue_draw()

    def set_bands(self, bands: list[float]) -> None:
        self._bars = interpolate_bars(bands, 36)
        self._peaks = tick_peaks(self._peaks, self._bars)
        self.queue_draw()

    def _hex(self, value: str) -> tuple[float, float, float]:
        v = value.lstrip("#")
        if len(v) == 3:
            v = "".join(ch * 2 for ch in v)
        r = int(v[0:2], 16) / 255.0
        g = int(v[2:4], 16) / 255.0
        b = int(v[4:6], 16) / 255.0
        return r, g, b

    def _draw(self, _area: Gtk.DrawingArea, cr: cairo.Context, width: int, height: int) -> None:
        cr.set_source_rgb(*self._hex(self.palette.bg))
        cr.rectangle(0, 0, width, height)
        cr.fill()
        n = len(self._bars)
        if n == 0 or width <= 0 or height <= 0:
            return
        gap = 1.6
        bar_w = max(3.0, (width - gap * (n + 1)) / n)
        segments = 10
        seg_h = max(2.0, (height - 6) / segments - 1.1)
        accent = self._hex(self.palette.accent)
        peak_c = self._hex(self.palette.peak)
        for i, value in enumerate(self._bars):
            x = gap + i * (bar_w + gap)
            lit = int(round(value * (segments - 1)))
            peak_seg = int(round(self._peaks[i] * (segments - 1)))
            for s in range(segments):
                y = height - 3 - (s + 1) * (seg_h + 1.1)
                if s <= lit:
                    if s >= segments - 2:
                        cr.set_source_rgb(*peak_c)
                    else:
                        t = 0.55 + 0.45 * (s / max(1, segments - 1))
                        cr.set_source_rgb(accent[0] * t, accent[1] * t, accent[2] * t)
                elif s == peak_seg:
                    cr.set_source_rgb(*peak_c)
                else:
                    cr.set_source_rgba(*accent, 0.10)
                cr.rectangle(x, y, bar_w, seg_h)
                cr.fill()
