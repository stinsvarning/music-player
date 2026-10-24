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
    wave_row,
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
TRAIL_ALPHA = (0.16, 0.07)
UNLIT_ALPHA = 0.08
GRID_ALPHA = 0.045

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
            s = cap - 1
            buckets[color(s, hot)].append((x, height - 2 - (s + 1) * seg + (seg - brick), col_w, brick))
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

    def put(color, c: int, k: int) -> None:
        x = ox + c * pitch + pad
        rects = buckets.setdefault(color, [])
        rects.append((x, oy + (half - 1 - k) * pitch + pad, size, size))
        rects.append((x, oy + (half + k) * pitch + pad, size, size))

    now = [wave_row(v, half) for v in interpolate_smooth(state.wave, cols)]
    for j, snap in enumerate(state.trail):
        if j >= len(TRAIL_ALPHA):
            break
        color = (*accent, TRAIL_ALPHA[j])
        for c, v in enumerate(interpolate_smooth(snap, cols)):
            k = wave_row(v, half)
            if k != now[c]:
                put(color, c, k)
    for c, k in enumerate(now):
        put(tones[max(1, k)], c, k)
        # join steps so the dots read as one continuous line
        if c > 0 and abs(now[c - 1] - k) > 1:
            lo, hi = sorted((now[c - 1], k))
            for kk in range(lo + 1, hi):
                put(tones[max(1, kk)], c if now[c - 1] < k else c - 1, kk)
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
    cr.set_source_rgb(*rgb(palette.bg))
    cr.rectangle(0, 0, width, height)
    cr.fill()
    if width < 8 or height < 8:
        return
    deck_l, deck_t, deck_r, deck_b = deck
    cell = max(4.0, width / FIELD_COLS)
    mid_x = (deck_l + deck_r) / 2 if deck_r > deck_l else width / 2
    mid_y = (deck_t + deck_b) / 2 if deck_b > deck_t else height / 2
    half = max(1.0, width / 2)
    dim = rgb(mix_hex(palette.bg, palette.accent, 0.28))
    mid = rgb(mix_hex(palette.bg, palette.accent, 0.55))
    lit = rgb(palette.accent)
    buckets: dict = {dim: [], mid: [], lit: []}
    bands = state.bands_for(mode)
    history = state.history if mode == "waterfall" else None
    amp = state.amp
    cols = int(math.ceil(width / cell)) + 2
    rows = int(math.ceil(height / cell)) + 2
    side = max(1, round(cell) - 1)
    for col in range(-1, cols):
        x = col * cell
        cx = x + cell / 2
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
            energy = shade * (0.30 + 0.52 * base * base + 0.18 * tw + amp * 0.22) * 0.34
            spec = field_spec(
                mode,
                cx=cx,
                cy=cy,
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
            if spec > 0:
                energy += spec * 0.72 * min(1.0, shade * 3)
            threshold = 0.78 * ((BAYER[(row & 7) * 8 + (col & 7)] + 0.5) / 64) + 0.22 * j
            if energy <= threshold:
                continue
            heat = spec * 0.55 + amp * 0.12
            color = lit if heat > 0.34 else mid if heat > 0.1 else dim
            buckets[color].append((round(x), round(y), side, side))
    _fill_buckets(cr, buckets)
