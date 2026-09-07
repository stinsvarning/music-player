from __future__ import annotations

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, Gtk

from music_player.spectrum import LOOKS, bar_index_at, cycle_look, interpolate_bars, tick_peaks
from music_player.theme import Palette, palette_named


class SpectrumView(Gtk.DrawingArea):
    def __init__(self) -> None:
        super().__init__()
        self.set_hexpand(True)
        self.set_content_height(44)
        self._bars = [0.0] * 36
        self._peaks = [0.0] * 36
        self._hover = -1
        self.look = LOOKS[0]
        self.palette: Palette = palette_named("mint")
        self.set_draw_func(self._draw)
        click = Gtk.GestureClick()
        click.connect("pressed", self._on_press)
        self.add_controller(click)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", lambda *_a: self._set_hover(-1))
        self.add_controller(motion)
        self.set_cursor(Gdk.Cursor.new_from_name("pointer"))

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette
        self.queue_draw()

    def set_bands(self, bands: list[float]) -> None:
        self._bars = interpolate_bars(bands, 36)
        self._peaks = tick_peaks(self._peaks, self._bars)
        self.queue_draw()

    def cycle_look(self) -> None:
        self.look = cycle_look(self.look)
        self.queue_draw()

    def _on_press(self, _g, _n, x, _y) -> None:
        self._set_hover(bar_index_at(x, self.get_width(), len(self._bars)))
        self.cycle_look()

    def _on_motion(self, _c, x, _y) -> None:
        self._set_hover(bar_index_at(x, self.get_width(), len(self._bars)))

    def _set_hover(self, idx: int) -> None:
        if idx == self._hover:
            return
        self._hover = idx
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
        if self.look == "mirror":
            self._draw_mirror(cr, width, height)
        else:
            self._draw_blocks(cr, width, height)

    def _layout(self, width: int, n: int) -> tuple[float, float]:
        gap = 1.6
        bar_w = max(3.0, (width - gap * (n + 1)) / n)
        return gap, bar_w

    def _bar_color(self, accent: tuple[float, float, float], hot: bool) -> tuple[float, float, float]:
        if hot:
            return (min(1.0, accent[0] * 1.25), min(1.0, accent[1] * 1.25), min(1.0, accent[2] * 1.25))
        return accent

    def _draw_blocks(self, cr: cairo.Context, width: int, height: int) -> None:
        n = len(self._bars)
        gap, bar_w = self._layout(width, n)
        segments = 10
        seg_h = max(2.0, (height - 6) / segments - 1.1)
        accent = self._hex(self.palette.accent)
        peak_c = self._hex(self.palette.peak)
        for i, value in enumerate(self._bars):
            x = gap + i * (bar_w + gap)
            color = self._bar_color(accent, i == self._hover)
            lit = int(round(value * (segments - 1)))
            peak_seg = int(round(self._peaks[i] * (segments - 1)))
            for s in range(segments):
                y = height - 3 - (s + 1) * (seg_h + 1.1)
                if s <= lit:
                    if s >= segments - 2:
                        cr.set_source_rgb(*peak_c)
                    else:
                        t = 0.55 + 0.45 * (s / max(1, segments - 1))
                        cr.set_source_rgb(color[0] * t, color[1] * t, color[2] * t)
                elif s == peak_seg:
                    cr.set_source_rgb(*peak_c)
                else:
                    cr.set_source_rgba(*color, 0.10)
                cr.rectangle(x, y, bar_w, seg_h)
                cr.fill()

    def _draw_mirror(self, cr: cairo.Context, width: int, height: int) -> None:
        n = len(self._bars)
        gap, bar_w = self._layout(width, n)
        accent = self._hex(self.palette.accent)
        peak_c = self._hex(self.palette.peak)
        mid = height / 2.0
        max_h = max(2.0, mid - 4)
        for i, value in enumerate(self._bars):
            x = gap + i * (bar_w + gap)
            color = self._bar_color(accent, i == self._hover)
            h = max(1.0, value * max_h)
            cr.set_source_rgb(*color)
            cr.rectangle(x, mid - h, bar_w, h * 2)
            cr.fill()
            peak_h = max(1.0, self._peaks[i] * max_h)
            cr.set_source_rgb(*peak_c)
            cr.rectangle(x, mid - peak_h - 1.2, bar_w, 2.0)
            cr.rectangle(x, mid + peak_h - 0.8, bar_w, 2.0)
            cr.fill()
