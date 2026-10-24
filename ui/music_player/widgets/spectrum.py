from __future__ import annotations

import time

import cairo
import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk

from music_player.spectrum import (
    BRICK_COLS,
    BRICK_SEGS,
    VIS_MODES,
    bar_index_at,
    brick_heights,
    decay_peaks,
    fill_orbit_brightness,
    smooth_levels,
    tick_brick_peaks,
    wave_reach,
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
        self._smooth = [0.0] * 10
        self._bars = [0.0] * BRICK_COLS
        self._cols = [0] * BRICK_COLS
        self._heights = [0.0] * BRICK_COLS
        self._peaks = [0] * BRICK_COLS
        self._reach = [0.0] * BRICK_COLS
        self._wave_hold = [0.0] * BRICK_COLS
        self._orbit = [0.0] * (BRICK_COLS * BRICK_SEGS)
        self._hover = -1
        self._clock = 0.0
        self._band_at = 0.0
        self._wave_at = 0.0
        self._rgb: tuple | None = None
        self.palette: Palette = palette_named("mint")
        self._cache_colors()
        self.set_draw_func(self._draw)
        self.set_cursor_from_name("pointer")
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", lambda *_a: self._set_hover(-1))
        self.add_controller(motion)
        click = Gtk.GestureClick()
        click.connect("released", self._on_click)
        self.add_controller(click)
        self.add_tick_callback(self._on_frame)

    def set_mode(self, mode: str) -> None:
        self.mode = mode if mode in VIS_MODES else VIS_MODES[0]
        self.queue_draw()

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette
        self._cache_colors()
        self.queue_draw()

    def set_bands(self, bands: list[float]) -> None:
        vals = [max(0.0, min(1.0, float(x))) for x in (bands or [])[:10]]
        while len(vals) < 10:
            vals.append(0.0)
        now = time.monotonic()
        dt = 1.0 / 20.0 if self._band_at <= 0.0 else min(0.1, max(0.0, now - self._band_at))
        self._band_at = now
        if self._clock <= 0.0:
            self._clock = now
        self._bands = vals
        self._smooth = smooth_levels(self._smooth, vals, dt)
        self._heights = brick_heights(self._smooth)
        self._cols = [max(0, min(BRICK_SEGS, int(round(h)))) for h in self._heights]
        self._peaks = tick_brick_peaks(self._peaks, self._cols)
        self._bars = [h / BRICK_SEGS for h in self._heights]
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

    def _on_frame(self, *_a) -> bool:
        # Bricks only move when a new spectrum frame arrives. Wave and orbit
        # keep a display-rate clock so the crest and the comets don't step at
        # the 80ms band period.
        if self.mode == "bricks" or not self.get_mapped():
            return True
        self._clock = time.monotonic()
        self.queue_draw()
        return True

    def _hex(self, value: str) -> tuple[float, float, float]:
        v = value.lstrip("#")
        if len(v) == 3:
            v = "".join(ch * 2 for ch in v)
        return int(v[0:2], 16) / 255.0, int(v[2:4], 16) / 255.0, int(v[4:6], 16) / 255.0

    def _cache_colors(self) -> None:
        low = self._hex(mix_hex(self.palette.bg, self.palette.accent, 0.50))
        mid = self._hex(self.palette.accent)
        high = self._hex(self.palette.peak)
        hot_mid = (min(1.0, mid[0] * 1.12), min(1.0, mid[1] * 1.12), min(1.0, mid[2] * 1.12))
        hot_high = (min(1.0, high[0] * 1.16), min(1.0, high[1] * 1.16), min(1.0, high[2] * 1.16))
        self._rgb = (low, mid, high, hot_mid, hot_high)

    def _colors(self):
        if self._rgb is None:
            self._cache_colors()
        return self._rgb

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

    def _metrics(self, width: int, height: int):
        cols = BRICK_COLS
        segs = BRICK_SEGS
        gap = 1.6
        col_w = (width - gap * (cols + 1)) / cols
        brick_h = (height - gap * (segs + 1)) / segs
        return cols, segs, gap, col_w, brick_h

    def _paint(self, cr, x, y, w, h, level: float, zone: int, hot: bool, colors, *, rail: bool = False) -> None:
        if w <= 0.4 or h <= 0.4:
            return
        low, mid, high, hot_mid, hot_high = colors
        if rail:
            cr.set_source_rgba(low[0], low[1], low[2], 0.34)
        elif level <= 0.03:
            cr.set_source_rgba(mid[0], mid[1], mid[2], 0.075)
        else:
            if zone >= 2:
                rgb = hot_high if hot else high
            elif zone == 1:
                rgb = hot_mid if hot else mid
            else:
                rgb = low
            alpha = 0.48 + 0.52 * level
            if alpha > 1.0:
                alpha = 1.0
            cr.set_source_rgba(rgb[0], rgb[1], rgb[2], alpha)
        cr.rectangle(x, y, w, h)
        cr.fill()

    def _cell_box(self, col: int, row: int, gap: float, col_w: float, brick_h: float, segs: int):
        # row 0 is the bottom of the strip
        x = gap + col * (col_w + gap)
        y = gap + (segs - 1 - row) * (brick_h + gap)
        return x, y

    def _zone_for_seg(self, seg: int) -> int:
        if seg >= 10:
            return 2
        if seg >= 6:
            return 1
        return 0

    def _draw_bricks(self, cr: cairo.Context, width: int, height: int) -> None:
        cols, segs, gap, col_w, brick_h = self._metrics(width, height)
        if col_w < 1.0 or brick_h < 1.0:
            return
        colors = self._colors()
        heights = self._heights
        peaks = self._peaks
        for i in range(cols):
            lit = heights[i] if i < len(heights) else 0.0
            peak = peaks[i] if i < len(peaks) else 0
            hot = i == self._hover
            x = gap + i * (col_w + gap)
            for s in range(segs):
                y = gap + (segs - 1 - s) * (brick_h + gap)
                if peak > 0 and s + 1 == peak and s >= lit:
                    level, zone = 1.0, 2
                elif s + 1 <= lit:
                    level, zone = 1.0, self._zone_for_seg(s)
                elif s < lit:
                    level, zone = lit - s, self._zone_for_seg(s)
                else:
                    level, zone = 0.0, 0
                self._paint(cr, x, y, col_w, brick_h, level, zone, hot, colors)

    def _advance_wave(self, t: float) -> None:
        n = len(self._bars)
        if len(self._reach) != n:
            self._reach = [0.0] * n
        for i in range(n):
            self._reach[i] = wave_reach(i, n, self._bars[i], t)
        if self._wave_at <= 0.0 or len(self._wave_hold) != n:
            self._wave_hold = list(self._reach)
        else:
            dt = min(0.08, max(0.0, t - self._wave_at))
            self._wave_hold = decay_peaks(self._wave_hold, self._reach, dt, fall=0.72)
        self._wave_at = t

    def _draw_wave(self, cr: cairo.Context, width: int, height: int) -> None:
        cols, segs, gap, col_w, brick_h = self._metrics(width, height)
        if col_w < 1.0 or brick_h < 1.0 or cols == 0:
            return
        t = self._clock if self._clock > 0.0 else time.monotonic()
        self._advance_wave(t)
        colors = self._colors()
        center = (segs - 1) / 2.0
        if center <= 0.0:
            return
        for i in range(cols):
            reach = self._reach[i] if i < len(self._reach) else 0.0
            hold = self._wave_hold[i] if i < len(self._wave_hold) else reach
            hot = i == self._hover
            x = gap + i * (col_w + gap)
            for s in range(segs):
                dist = abs(s - center) / center
                y = gap + (segs - 1 - s) * (brick_h + gap)
                if dist <= reach:
                    overhang = (reach - dist) * center
                    level = 1.0 if overhang >= 1.0 else 0.42 + 0.58 * overhang
                    if dist > 0.74:
                        zone = 2
                    elif dist > 0.40:
                        zone = 1
                    else:
                        zone = 0
                elif hold > reach + 0.04 and abs(dist - hold) <= 0.62 / center:
                    level, zone = 1.0, 2
                else:
                    level, zone = 0.0, 0
                self._paint(cr, x, y, col_w, brick_h, level, zone, hot, colors)

    def _draw_orbit(self, cr: cairo.Context, width: int, height: int) -> None:
        cols, segs, gap, col_w, brick_h = self._metrics(width, height)
        if col_w < 1.0 or brick_h < 1.0:
            return
        n = cols * segs
        if len(self._orbit) != n:
            self._orbit = [0.0] * n
        t = self._clock if self._clock > 0.0 else time.monotonic()
        fill_orbit_brightness(self._orbit, self._smooth, t, cols, segs)
        colors = self._colors()
        mask = self._orbit
        for row in range(segs):
            for col in range(cols):
                b = mask[row * cols + col]
                x, y = self._cell_box(col, row, gap, col_w, brick_h, segs)
                hot = col == self._hover
                if b >= 0.90:
                    self._paint(cr, x, y, col_w, brick_h, 1.0, 2, hot, colors)
                elif b >= 0.55:
                    self._paint(cr, x, y, col_w, brick_h, b, 1, hot, colors)
                elif b >= 0.30:
                    self._paint(cr, x, y, col_w, brick_h, b, 0, hot, colors)
                elif b > 0.05:
                    self._paint(cr, x, y, col_w, brick_h, b, 0, hot, colors, rail=True)
                else:
                    self._paint(cr, x, y, col_w, brick_h, 0.0, 0, hot, colors)
