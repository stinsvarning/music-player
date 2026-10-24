"""Cairo painters for the LCD strip and the background field.

Cairo only (no GTK), so the widgets and tools/vis_preview.py share the exact
same drawing code. Rectangles are batched per colour: one fill per tone.
"""

from __future__ import annotations

import math

import cairo

from music_player.spectrum import (
    BRICK_SEGS,
    FIELD_COLS,
    WATERFALL_ROWS,
    WATERFALL_STEPS,
    WAVE_ROWS,
    FieldState,
    LcdState,
    field_clearance,
    field_spec,
    interpolate_smooth,
    wave_heights,
    waterfall_step,
)
from music_player.theme import Palette, mix_hex

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
TRAIL_ALPHA = (0.10, 0.045)
UNLIT_ALPHA = 0.08
GRID_ALPHA = 0.045
FIELD_GRID_ALPHA = 0.025  # the field's unlit cells; 0 for pure black at rest
FIELD_GAIN = 0.8
FIELD_LIFT = 0.22  # cells the music touches get the same lift the old idle dither gave

_RGB: dict[str, tuple[float, float, float]] = {}
_TONES: dict[tuple, list[tuple[float, float, float]]] = {}
_GRIDS: dict[tuple, cairo.ImageSurface] = {}


def rgb(value: str) -> tuple[float, float, float]:
    hit = _RGB.get(value)
    if hit is not None:
        return hit
    v = value.lstrip("#")
    if len(v) == 3:
        v = "".join(ch * 2 for ch in v)
    out = (int(v[0:2], 16) / 255.0, int(v[2:4], 16) / 255.0, int(v[4:6], 16) / 255.0)
    _RGB[value] = out
    return out


def lcd_bg(palette: Palette) -> str:
    return mix_hex(palette.bg, "#000000", 0.45)


def tone_ramp(palette: Palette, steps: int, start: float = 0.12, knee: float = 0.7) -> list[tuple[float, float, float]]:
    """steps+1 colours: [0] is the LCD background, then dim accent -> accent -> peak."""
    key = (palette.bg, palette.accent, palette.peak, steps, start, knee)
    hit = _TONES.get(key)
    if hit is not None:
        return hit
    base = lcd_bg(palette)
    out = [rgb(base)]
    for i in range(1, steps + 1):
        t = i / steps
        if t <= knee:
            out.append(rgb(mix_hex(base, palette.accent, start + (1.0 - start) * (t / knee))))
        else:
            out.append(rgb(mix_hex(palette.accent, palette.peak, (t - knee) / (1.0 - knee))))
    _TONES[key] = out
    return out


def _fill_buckets(cr: cairo.Context, buckets: dict) -> None:
    for color, rects in buckets.items():
        if not rects:
            continue
        if len(color) == 4:
            cr.set_source_rgba(*color)
        else:
            cr.set_source_rgb(*color)
        for x, y, w, h in rects:
            cr.rectangle(x, y, w, h)
        cr.fill()


def _cached_grid(cr: cairo.Context, key: tuple, width: int, height: int, draw) -> None:
    """Paint a static layer (LCD bg plus unlit cells) from a per-size cache."""
    sx, sy = cr.user_to_device_distance(1.0, 1.0)
    sx, sy = abs(sx) or 1.0, abs(sy) or 1.0
    full = key + (width, height, round(sx, 3), round(sy, 3))
    surf = _GRIDS.get(full)
    if surf is None:
        if len(_GRIDS) > 12:
            _GRIDS.clear()
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, max(1, int(math.ceil(width * sx))), max(1, int(math.ceil(height * sy))))
        g = cairo.Context(surf)
        g.scale(sx, sy)
        draw(g)
        surf.flush()
        _GRIDS[full] = surf
    cr.save()
    cr.scale(1.0 / sx, 1.0 / sy)
    cr.set_source_surface(surf, 0, 0)
    cr.paint()
    cr.restore()


# ------------------------------------------------------------------ LCD


def paint_lcd(
    cr: cairo.Context,
    width: int,
    height: int,
    mode: str,
    palette: Palette,
    state: LcdState,
    hover: int = -1,
) -> None:
    if width <= 0 or height <= 0:
        return
    if mode == "wave":
        _paint_wave(cr, width, height, palette, state)
    elif mode == "waterfall":
        _paint_waterfall(cr, width, height, palette, state)
    else:
        _paint_bricks(cr, width, height, palette, state, hover)


def _brick_geom(width: int, height: int, n: int) -> tuple[float, float, float, float]:
    gap = 1.5
    col_w = max(2.0, (width - gap * (n + 1)) / n)
    seg = max(3.5, (height - 4) / BRICK_SEGS)
    brick = max(2.0, seg - 1.6)
    return gap, col_w, seg, brick


def _paint_bricks(cr, width, height, palette: Palette, state: LcdState, hover: int) -> None:
    n = len(state.bars)
    if n == 0:
        return
    gap, col_w, seg, brick = _brick_geom(width, height, n)
    bg = rgb(lcd_bg(palette))
    mid = rgb(palette.accent)

    def grid(g: cairo.Context) -> None:
        g.set_source_rgb(*bg)
        g.paint()
        g.set_source_rgba(*mid, UNLIT_ALPHA)
        for i in range(n):
            x = gap + i * (col_w + gap)
            for s in range(BRICK_SEGS):
                g.rectangle(x, height - 2 - (s + 1) * seg + (seg - brick), col_w, brick)
        g.fill()

    _cached_grid(cr, ("bricks", bg, mid), width, height, grid)
    low = rgb(mix_hex(palette.bg, palette.accent, 0.45))
    high = rgb(palette.peak)
    hot_mid = tuple(min(1.0, c * 1.15) for c in mid)
    hot_high = tuple(min(1.0, c * 1.2) for c in high)
    buckets: dict = {low: [], mid: [], high: [], hot_mid: [], hot_high: []}

    def color(s: int, hot: bool):
        if s >= 10:
            return hot_high if hot else high
        if s >= 6:
            return hot_mid if hot else mid
        return low

    for i, bar in enumerate(state.bars):
        lit = max(0, min(BRICK_SEGS, int(round(bar * BRICK_SEGS))))
        cap = max(0, min(BRICK_SEGS, int(round(state.peaks[i] * BRICK_SEGS)))) if i < len(state.peaks) else 0
        x = gap + i * (col_w + gap)
        hot = i == hover
        for s in range(lit):
            buckets[color(s, hot)].append((x, height - 2 - (s + 1) * seg + (seg - brick), col_w, brick))
        if cap > lit:
            s = cap - 1  # a fresh cap pops in the peak tone, then falls in the accent tone
            fresh = i < len(state.peak_holds) and state.peak_holds[i] > 0
            buckets[(hot_high if hot else high) if fresh else (hot_mid if hot else mid)].append((x, height - 2 - (s + 1) * seg + (seg - brick), col_w, brick))
    _fill_buckets(cr, buckets)


def _wave_geom(width: int, height: int) -> tuple[int, int, int, int, int]:
    pitch = max(3, int(height // WAVE_ROWS))
    cols = max(1, int(width // pitch))
    ox = int((width - cols * pitch) // 2)
    oy = int((height - WAVE_ROWS * pitch) // 2)
    size = max(2, pitch - 2)
    return pitch, cols, ox, oy, size


def _paint_wave(cr, width, height, palette: Palette, state: LcdState) -> None:
    pitch, cols, ox, oy, size = _wave_geom(width, height)
    half = WAVE_ROWS // 2
    bg = rgb(lcd_bg(palette))
    accent = rgb(palette.accent)
    pad = (pitch - size) / 2

    def grid(g: cairo.Context) -> None:
        g.set_source_rgb(*bg)
        g.paint()
        g.set_source_rgba(*accent, GRID_ALPHA)
        for c in range(cols):
            for r in range(WAVE_ROWS):
                g.rectangle(ox + c * pitch + pad, oy + r * pitch + pad, size, size)
        g.fill()

    _cached_grid(cr, ("wave", bg, accent), width, height, grid)
    tones = tone_ramp(palette, half - 1, start=0.58, knee=0.7)
    buckets: dict = {}
    steps = 6  # alpha steps for the in-between rows

    def put(c: int, k: int, alpha: float, tone=None) -> None:
        if alpha <= 0.5 / steps or k < 0 or k >= half:
            return
        a = round(alpha * steps) / steps
        base = tone if tone is not None else tones[max(1, k)]
        key = base if a >= 1.0 else (*base, a)
        rects = buckets.setdefault(key, [])
        x = ox + c * pitch + pad
        rects.append((x, oy + (half - 1 - k) * pitch + pad, size, size))
        rects.append((x, oy + (half + k) * pitch + pad, size, size))

    def line(heights: list[float], alpha: float, tone=None) -> None:
        prev = None
        for c, h in enumerate(heights):
            k = int(h)
            f = h - k
            # hand the dot over between rows only around the midpoint, so the line
            # moves continuously without looking doubled
            w = min(1.0, max(0.0, (f - 0.3) / 0.4))
            put(c, k, alpha * (1.0 - w), tone)
            put(c, k + 1, alpha * w, tone)
            if prev is not None and abs(h - prev) > 1.0:
                lo, hi = sorted((prev, h))
                for kk in range(int(lo) + 1, int(hi) + (1 if hi % 1 > 0.5 else 0)):
                    put(c, kk, alpha * 0.55, tone)
            prev = h

    for j, (snap, phase, energy) in enumerate(state.trail):
        if j >= len(TRAIL_ALPHA):
            break
        line(wave_heights(snap, cols, half, phase, energy), TRAIL_ALPHA[j] / 0.6, accent)
    line(wave_heights(state.wave, cols, half, state.phase, state.energy), 1.0)
    _fill_buckets(cr, buckets)


def _waterfall_geom(width: int, height: int) -> tuple[int, int, int, int, int]:
    pitch = max(3, int((height - 2) // WATERFALL_ROWS))
    cols = max(1, int((width - 2) // pitch))
    size = max(2, pitch - 2)
    ox = int((width - cols * pitch) // 2)
    oy = int((height - WATERFALL_ROWS * pitch) // 2)
    return pitch, cols, ox, oy, size


def _paint_waterfall(cr, width, height, palette: Palette, state: LcdState) -> None:
    pitch, cols, ox, oy, size = _waterfall_geom(width, height)
    bg = rgb(lcd_bg(palette))
    accent = rgb(palette.accent)
    pad = (pitch - size) / 2

    def grid(g: cairo.Context) -> None:
        g.set_source_rgb(*bg)
        g.paint()
        g.set_source_rgba(*accent, GRID_ALPHA)
        for c in range(cols):
            for r in range(WATERFALL_ROWS):
                g.rectangle(ox + c * pitch + pad, oy + r * pitch + pad, size, size)
        g.fill()

    _cached_grid(cr, ("waterfall", bg, accent), width, height, grid)
    tones = tone_ramp(palette, WATERFALL_STEPS, start=0.14, knee=0.72)
    buckets: dict = {}
    hist = state.history
    n = len(hist)
    for c in range(cols):
        idx = n - cols + c  # newest column on the right, time scrolls left
        if idx < 0:
            continue
        frame = hist[idx]
        x = ox + c * pitch + pad
        for b in range(WATERFALL_ROWS):
            step = waterfall_step(frame[b])
            if step <= 0:
                continue
            buckets.setdefault(tones[step], []).append((x, oy + (WATERFALL_ROWS - 1 - b) * pitch + pad, size, size))
    _fill_buckets(cr, buckets)


# ---------------------------------------------------------------- field


def paint_field(
    cr: cairo.Context,
    width: int,
    height: int,
    deck: tuple[float, float, float, float],
    mode: str,
    palette: Palette,
    state: FieldState,
    t: float,
) -> None:
    """Dark at rest: a faint cell grid, lit only where the mode's music response drives it."""
    if width < 8 or height < 8:
        cr.set_source_rgb(*rgb(palette.bg))
        cr.rectangle(0, 0, width, height)
        cr.fill()
        return
    deck_l, deck_t, deck_r, deck_b = deck
    cell = max(4.0, width / FIELD_COLS)
    mid_x = (deck_l + deck_r) / 2 if deck_r > deck_l else width / 2
    mid_y = (deck_t + deck_b) / 2 if deck_b > deck_t else height / 2
    half = max(1.0, width / 2)
    cols = int(math.ceil(width / cell)) + 2
    rows = int(math.ceil(height / cell)) + 2
    side = max(1, round(cell) - 1)
    bg = rgb(palette.bg)
    accent = rgb(palette.accent)

    # per-column / per-row distance outside the deck, and the deck clearance
    col_dx = []
    for col in range(-1, cols):
        cx = col * cell + cell / 2
        col_dx.append(max(deck_l - cx, 0.0, cx - deck_r) if deck_r > deck_l else 0.0)
    row_dy = []
    for row in range(-1, rows):
        cy = row * cell + cell / 2
        row_dy.append(max(deck_t - cy, 0.0, cy - deck_b) if deck_b > deck_t else 0.0)

    def grid(g: cairo.Context) -> None:
        g.set_source_rgb(*bg)
        g.paint()
        if FIELD_GRID_ALPHA <= 0:
            return
        for ri, row in enumerate(range(-1, rows)):
            for ci, col in enumerate(range(-1, cols)):
                shade = field_clearance(col_dx[ci], row_dy[ri])
                if shade < 0.05:
                    continue
                g.set_source_rgba(*accent, FIELD_GRID_ALPHA * shade)
                g.rectangle(round(col * cell), round(row * cell), side, side)
                g.fill()

    _cached_grid(cr, ("field", bg, accent, round(deck_l), round(deck_t), round(deck_r), round(deck_b)), width, height, grid)

    dim = rgb(mix_hex(palette.bg, palette.accent, 0.28))
    mid = rgb(mix_hex(palette.bg, palette.accent, 0.55))
    lit = accent
    buckets: dict = {dim: [], mid: [], lit: []}
    bands = state.bands_for(mode)
    history = state.history if mode == "waterfall" else None
    for ci, col in enumerate(range(-1, cols)):
        x = col * cell
        cx = x + cell / 2
        dx = col_dx[ci]
        for ri, row in enumerate(range(-1, rows)):
            dy = row_dy[ri]
            shade = field_clearance(dx, dy)
            if shade < 0.004:
                continue
            y = row * cell
            spec = field_spec(
                mode,
                cx=cx,
                cy=y + cell / 2,
                mid_x=mid_x,
                mid_y=mid_y,
                half=half,
                height=height,
                cell=cell,
                bands=bands,
                t=t,
                ring=max(dx, dy),
                history=history,
            )
            if spec <= 0:
                continue
            energy = (spec * FIELD_GAIN + FIELD_LIFT * min(1.0, spec / 0.08)) * min(1.0, shade * 3)
            j = JITTER[(row * 37 + col * 11) & 4095]
            threshold = 0.78 * ((BAYER[(row & 7) * 8 + (col & 7)] + 0.5) / 64) + 0.22 * j
            if energy <= threshold:
                continue
            heat = spec * 0.6
            color = lit if heat > 0.34 else mid if heat > 0.1 else dim
            buckets[color].append((round(x), round(y), side, side))
    _fill_buckets(cr, buckets)
