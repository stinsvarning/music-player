from __future__ import annotations

import math

import cairo
import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk

from music_player.spectrum import (
    BRICK_COLS,
    BRICK_SEGS,
    VIS_MODES,
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
        self.mode = VIS_MODES[0]
        self.on_cycle = None
        self._bands = [0.0] * 10
        self._cols = [0] * BRICK_COLS
        self._peaks = [0] * BRICK_COLS
        self._hover = -1
        self.palette: Palette = palette_named("mint")
        self.set_draw_func(self._draw)
        self.set_cursor_from_name("pointer")
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", lambda *_a: self._set_hover(-1))
        self.add_controller(motion)
        click = Gtk.GestureClick()
        click.connect("released", self._on_click)
        self.add_controller(click)

    def set_mode(self, mode: str) -> None:
        self.mode = mode if mode in VIS_MODES else VIS_MODES[0]
        self.queue_draw()

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette
        self.queue_draw()

    def set_bands(self, bands: list[float]) -> None:
        vals = [max(0.0, min(1.0, float(x))) for x in (bands or [])[:10]]
        while len(vals) < 10:
            vals.append(0.0)
        self._bands = vals
        self._cols = brick_columns(vals)
        self._peaks = tick_brick_peaks(self._peaks, self._cols)
        self.queue_draw()

    def _on_click(self, *_a) -> None:
        if callable(self.on_cycle):
            self.on_cycle()

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
        if width <= 0 or height <= 0:
            return
        if self.mode == "wave":
            self._draw_wave(cr, width, height)
            return
        if self.mode == "orbit":
            self._draw_orbit(cr, width, height)
            return
        self._draw_bricks(cr, width, height)

    def _brick_colors(self):
        low = self._hex(mix_hex(self.palette.bg, self.palette.accent, 0.45))
        mid = self._hex(self.palette.accent)
        high = self._hex(self.palette.peak)
        return low, mid, high

    def _paint_brick(self, cr, *, on: bool, seg: int, hot: bool, low, mid, high) -> None:
        if not on:
            cr.set_source_rgba(*mid, 0.08)
        elif seg >= 10:
            cr.set_source_rgb(*(high if not hot else tuple(min(1.0, c * 1.2) for c in high)))
        elif seg >= 6:
            cr.set_source_rgb(*(mid if not hot else tuple(min(1.0, c * 1.15) for c in mid)))
        else:
            cr.set_source_rgb(*low)

    def _draw_wave(self, cr: cairo.Context, width: int, height: int) -> None:
        n = len(self._cols)
        if n == 0:
            return
        gap = 1.5
        col_w = max(2.0, (width - gap * (n + 1)) / n)
        seg_h = max(3.0, (height / 2 - 3) / BRICK_SEGS)
        brick = max(2.0, seg_h - 1.4)
        low, mid, high = self._brick_colors()
        mid_y = height / 2
        for i, lit in enumerate(self._cols):
            x = gap + i * (col_w + gap)
            hot = i == self._hover
            peak = self._peaks[i] if i < len(self._peaks) else lit
            for s in range(BRICK_SEGS):
                self._paint_brick(cr, on=s < lit or s + 1 == peak, seg=s, hot=hot, low=low, mid=mid, high=high)
                cr.rectangle(x, mid_y - (s + 1) * seg_h + (seg_h - brick), col_w, brick)
                cr.fill()
                cr.rectangle(x, mid_y + s * seg_h, col_w, brick)
                cr.fill()

    def _draw_orbit(self, cr: cairo.Context, width: int, height: int) -> None:
        n = len(self._cols)
        if n == 0:
            return
        cx, cy = width / 2, height / 2
        radius = min(width, height) * 0.46
        inner = radius * 0.22
        step = (radius - inner) / BRICK_SEGS
        brick = max(2.0, step - 1.5)
        half_w = max(1.4, math.pi * radius / n * 0.38)
        low, mid, high = self._brick_colors()
        for i, lit in enumerate(self._cols):
            ang = -math.pi / 2 + (i / n) * math.tau
            ca, sa = math.cos(ang), math.sin(ang)
            px, py = -sa, ca
            hot = i == self._hover
            peak = self._peaks[i] if i < len(self._peaks) else lit
            for s in range(BRICK_SEGS):
                self._paint_brick(cr, on=s < lit or s + 1 == peak, seg=s, hot=hot, low=low, mid=mid, high=high)
                r0 = inner + s * step
                r1 = r0 + brick
                w = half_w * (0.45 + 0.55 * ((r0 + r1) / 2) / radius)
                cr.move_to(cx + ca * r0 + px * w, cy + sa * r0 + py * w)
                cr.line_to(cx + ca * r0 - px * w, cy + sa * r0 - py * w)
                cr.line_to(cx + ca * r1 - px * w, cy + sa * r1 - py * w)
                cr.line_to(cx + ca * r1 + px * w, cy + sa * r1 + py * w)
                cr.close_path()
                cr.fill()

    def _draw_bricks(self, cr: cairo.Context, width: int, height: int) -> None:
        n = len(self._cols)
        if n == 0:
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
                self._paint_brick(cr, on=s < lit or s + 1 == peak, seg=s, hot=hot, low=low, mid=mid, high=high)
                cr.rectangle(x, y + (seg - brick), col_w, brick)
                cr.fill()
