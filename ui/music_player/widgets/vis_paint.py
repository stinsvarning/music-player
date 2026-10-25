"""Cairo painters for the LCD strip and the background field.

Cairo only (no GTK), so the widgets and tools/vis_preview.py share the exact
same drawing code. Rectangles are batched per colour: one fill per tone.
"""

from __future__ import annotations

import math

import cairo

from music_player.spectrum import (
    VIS_OFF,
    BRICK_SEGS,
    FIELD_BRICK_TALL,
    FIELD_COLS,
    WATERFALL_ROWS,
    WATERFALL_STEPS,
    WAVE_ROWS,
    FieldState,
    LcdState,
    band_at_height,
    bass_of,
    clamp01,
    field_band_at,
    field_clearance,
    gate,
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


def _device_scale(cr: cairo.Context) -> tuple[float, float]:
    sx, sy = cr.user_to_device_distance(1.0, 1.0)
    return abs(sx) or 1.0, abs(sy) or 1.0


def render_layer(width: int, height: int, sx: float, sy: float, draw) -> cairo.ImageSurface:
    """Paint `draw` once into an opaque device-resolution surface."""
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, max(1, int(math.ceil(width * sx))), max(1, int(math.ceil(height * sy))))
    g = cairo.Context(surf)
    g.scale(sx, sy)
    draw(g)
    surf.flush()
    return surf


def _paint_layer(cr: cairo.Context, surf: cairo.ImageSurface, sx: float, sy: float) -> None:
    cr.save()
    cr.scale(1.0 / sx, 1.0 / sy)
    cr.set_source_surface(surf, 0, 0)
    cr.paint()
    cr.restore()


def _cached_grid(cr: cairo.Context, key: tuple, width: int, height: int, draw) -> None:
    """Paint a static layer (LCD bg plus unlit cells) from a per-size cache."""
    sx, sy = _device_scale(cr)
    full = key + (width, height, round(sx, 3), round(sy, 3))
    surf = _GRIDS.get(full)
    if surf is None:
        if len(_GRIDS) > 12:
            _GRIDS.clear()
        surf = _GRIDS[full] = render_layer(width, height, sx, sy, draw)
    _paint_layer(cr, surf, sx, sy)


# ------------------------------------------------------------------ LCD


_REST: list = []


def _rest_lcd() -> LcdState:
    if not _REST:
        _REST.append(LcdState())
    return _REST[0]


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
    if mode == VIS_OFF:
        # off: the bricks grid at rest (unlit cells only), whatever the state holds
        _paint_bricks(cr, width, height, palette, _rest_lcd(), -1)
    elif mode == "wave":
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

    tones = tone_ramp(palette, half - 1, start=0.58, knee=0.7)
    buckets: dict = {}
    steps = 6  # alpha steps for the in-between rows

    # Dot positions are fixed per size; put() runs a few hundred times a frame.
    xs = [ox + c * pitch + pad for c in range(cols)]
    tops = [oy + (half - 1 - k) * pitch + pad for k in range(half)]
    bottoms = [oy + (half + k) * pitch + pad for k in range(half)]
    least = 0.5 / steps

    def put(c: int, k: int, alpha: float, tone=None) -> None:
        if alpha <= least or k < 0 or k >= half:
            return
        a = round(alpha * steps) / steps
        base = tone if tone is not None else tones[k if k > 1 else 1]
        key = base if a >= 1.0 else (*base, a)
        rects = buckets.get(key)
        if rects is None:
            rects = buckets[key] = []
        x = xs[c]
        rects.append((x, tops[k], size, size))
        rects.append((x, bottoms[k], size, size))

    def line(heights: list[float], alpha: float, tone=None) -> None:
        prev = None
        for c, h in enumerate(heights):
            k = int(h)
            f = h - k
            # hand the dot over between rows only around the midpoint, so the line
            # moves continuously without looking doubled
            w = (f - 0.3) / 0.4
            w = 0.0 if w <= 0.0 else 1.0 if w >= 1.0 else w
            put(c, k, alpha * (1.0 - w), tone)
            put(c, k + 1, alpha * w, tone)
            if prev is not None and abs(h - prev) > 1.0:
                lo, hi = sorted((prev, h))
                for kk in range(int(lo) + 1, int(hi) + (1 if hi % 1 > 0.5 else 0)):
                    put(c, kk, alpha * 0.55, tone)
            prev = h

    def trail(_buckets: dict) -> None:
        for j, (snap, phase, energy) in enumerate(state.trail):
            if j >= len(TRAIL_ALPHA):
                break
            line(wave_heights(snap, cols, half, phase, energy), TRAIL_ALPHA[j] / 0.6, accent)

    # The trail lines only change when new bands arrive (~12 times a second), so
    # they are drawn once per band update into a layer with the grid, and only the
    # live line is laid out per frame. That is the same picture as filling all
    # buckets in one go as long as the trail and the live line never share a fill
    # colour (they would be one union fill then); the trail is the plain accent, so
    # this holds unless the theme puts the accent itself on the tone ramp.
    sx, sy = _device_scale(cr)
    trail_key = (state.serial, len(state.trail), width, height, round(sx, 3), round(sy, 3), bg, accent, tuple(tones))
    if accent in tones[1:]:
        _cached_grid(cr, ("wave", bg, accent), width, height, grid)
        trail(buckets)
    else:
        cached = getattr(state, "_trail_dots", None)
        if cached is None or cached[0] != trail_key:

            def layer(g: cairo.Context) -> None:
                _cached_grid(g, ("wave", bg, accent), width, height, grid)
                trail(buckets)
                _fill_buckets(g, buckets)

            cached = state._trail_dots = (trail_key, render_layer(width, height, sx, sy, layer))
            buckets.clear()
        _paint_layer(cr, cached[1], sx, sy)
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
#
# The field is ~2,600 cells on a 4K-wide window and redraws on every band poll.
# Everything that depends only on the geometry (each cell's position, deck
# clearance, dither threshold) is computed once per size; per poll only the
# mode's music response is evaluated, column by column, with the same arithmetic
# as spectrum.field_spec so the lit cells are exactly the same.


class FieldGeom:
    """Per-size constants of the field grid; see field_geom."""

    __slots__ = ("cell", "side", "mid_x", "mid_y", "half", "cols", "rows", "colinfo", "rowinfo", "by_col", "key")


_GEOMS: dict[tuple, FieldGeom] = {}


def field_geom(width: int, height: int, deck: tuple[float, float, float, float]) -> FieldGeom:
    key = (width, height, tuple(deck))
    hit = _GEOMS.get(key)
    if hit is not None:
        return hit
    if len(_GEOMS) > 8:
        _GEOMS.clear()
    deck_l, deck_t, deck_r, deck_b = deck
    g = FieldGeom()
    g.key = key
    g.cell = cell = max(4.0, width / FIELD_COLS)
    g.mid_x = (deck_l + deck_r) / 2 if deck_r > deck_l else width / 2
    g.mid_y = (deck_t + deck_b) / 2 if deck_b > deck_t else height / 2
    g.half = max(1.0, width / 2)
    g.cols = cols = int(math.ceil(width / cell)) + 2
    g.rows = rows = int(math.ceil(height / cell)) + 2
    g.side = max(1, round(cell) - 1)
    g.colinfo = []  # (col, x, cx, dx)
    for col in range(-1, cols):
        x = col * cell
        cx = x + cell / 2
        g.colinfo.append((col, x, cx, max(deck_l - cx, 0.0, cx - deck_r) if deck_r > deck_l else 0.0))
    g.rowinfo = []  # (row, y, cy, dy)
    for row in range(-1, rows):
        y = row * cell
        cy = y + cell / 2
        g.rowinfo.append((row, y, cy, max(deck_t - cy, 0.0, cy - deck_b) if deck_b > deck_t else 0.0))
    # Per column, the cells the deck does not hide: (row index, shade factor, dither threshold, rect).
    g.by_col = []
    for col, x, _cx, dx in g.colinfo:
        cells = []
        for ri, (row, y, _cy, dy) in enumerate(g.rowinfo):
            shade = field_clearance(dx, dy)
            if shade < 0.004:
                continue
            j = JITTER[(row * 37 + col * 11) & 4095]
            threshold = 0.78 * ((BAYER[(row & 7) * 8 + (col & 7)] + 0.5) / 64) + 0.22 * j
            cells.append((ri, min(1.0, shade * 3), threshold, (round(x), round(y), g.side, g.side)))
        g.by_col.append(cells)
    _GEOMS[key] = g
    return g


def _field_cell_light(spec: float, shade3: float, threshold: float, heat_gain: float) -> int:
    """0 = unlit, else 1 dim / 2 mid / 3 lit (the field_spec -> dither -> tone step)."""
    energy = (spec * FIELD_GAIN + FIELD_LIFT * min(1.0, spec / 0.08)) * shade3
    if energy <= threshold:
        return 0
    heat = spec * heat_gain
    return 3 if heat > 0.34 else 2 if heat > 0.1 else 1


def field_cells(geom: FieldGeom, height: int, mode: str, state: FieldState, t: float) -> tuple[list, list, list]:
    """Rects of the lit field cells per tone (dim, mid, lit); pure, so it can be compared and cached."""
    out: tuple[list, list, list] = ([], [], [])
    if mode == VIS_OFF:
        return out  # off: the bare grid
    tone = (None, out[0], out[1], out[2])
    bands = state.bands_for(mode)
    cell = geom.cell
    heat_gain = 0.66 if mode in ("bricks", "wave") else 0.6
    rowinfo = geom.rowinfo
    if mode == "wave":
        # field_spec("wave"), split into per-draw, per-column and per-row parts
        swell = gate(bass_of(bands), 0.04, 1.1)
        if swell <= 0:
            return out
        mid_x, mid_y, half = geom.mid_x, geom.mid_y, geom.half
        near = cell * 0.5
        glow_k = 0.55 + 0.75 * swell
        line_k = min(1.0, swell * 4.0)
        for (_col, _x, cx, _dx), cells in zip(geom.colinfo, geom.by_col):
            side = clamp01(abs(cx - mid_x) / max(1.0, half))
            reach = clamp01((side - 0.22) / 0.78) ** 0.9
            if reach <= 0:
                continue
            line_v = 0.16 * reach * line_k
            undulate = 0.9 + 0.1 * math.sin(t * 0.5 + side * 2.2)
            thick = cell * 0.5 + swell * reach * height * 0.36 * undulate
            glow_a = min(1.0, glow_k * (0.45 + 0.55 * reach))
            for ri, shade3, threshold, rect in cells:
                d = abs(rowinfo[ri][2] - mid_y)
                line = line_v if d < near else 0.0
                if d >= thick:
                    spec = line
                else:
                    glow = glow_a * (1.0 - d / thick) ** 0.9
                    spec = max(line, glow)
                if spec <= 0:
                    continue
                k = _field_cell_light(spec, shade3, threshold, heat_gain)
                if k:
                    tone[k].append(rect)
        return out
    if mode == "waterfall":
        history = state.history
        if not history:
            return out
        n = len(history)
        half = geom.half
        rings: dict = {}
        for (_col, _x, _cx, dx), cells in zip(geom.colinfo, geom.by_col):
            for ri, shade3, threshold, rect in cells:
                ring = max(dx, rowinfo[ri][3])
                age = int(ring / cell)
                if age >= n:
                    continue
                key = (ri, age)
                level = rings.get(key)
                if level is None:
                    level = rings[key] = gate(band_at_height(rowinfo[ri][2], height, history[n - 1 - age]), 0.10, 1.1)
                if level <= 0:
                    continue
                fade = max(0.0, 1.0 - ring / max(1.0, half))
                spec = min(1.0, level * 1.3 * (0.25 + 0.75 * fade**1.4))
                if spec <= 0:
                    continue
                k = _field_cell_light(spec, shade3, threshold, heat_gain)
                if k:
                    tone[k].append(rect)
        return out
    # bricks
    mid_x, half = geom.mid_x, geom.half
    for (_col, _x, cx, _dx), cells in zip(geom.colinfo, geom.by_col):
        level = gate(field_band_at(cx, mid_x, half, bands), 0.02, 1.25)
        if level <= 0:
            continue
        tall = level * (height / cell) * FIELD_BRICK_TALL
        for ri, shade3, threshold, rect in cells:
            up = (height - rowinfo[ri][2]) / cell
            if not (0 <= up < tall):
                continue
            spec = min(1.0, level * (0.45 + 0.55 * (1 - up / tall) ** 0.7) * 1.25)
            if spec <= 0:
                continue
            k = _field_cell_light(spec, shade3, threshold, heat_gain)
            if k:
                tone[k].append(rect)
    return out


def field_tones(palette: Palette) -> tuple[tuple, tuple, tuple]:
    """(dim, mid, lit) colours of the lit field cells."""
    return (
        rgb(mix_hex(palette.bg, palette.accent, 0.28)),
        rgb(mix_hex(palette.bg, palette.accent, 0.55)),
        rgb(palette.accent),
    )


def field_grid_draw(geom: FieldGeom, palette: Palette):
    """The static layer: one uniform dark with faint cells; (cache key, painter)."""
    bg = rgb(palette.bg)
    accent = rgb(palette.accent)
    cell, side = geom.cell, geom.side
    rows, cols = geom.rows, geom.cols

    def grid(g: cairo.Context) -> None:
        # One uniform dark everywhere: the faint cells run right up to the deck
        # (which covers them), so there is no darker halo around it.
        g.set_source_rgb(*bg)
        g.paint()
        if FIELD_GRID_ALPHA <= 0:
            return
        g.set_source_rgba(*accent, FIELD_GRID_ALPHA)
        for row in range(-1, rows):
            for col in range(-1, cols):
                g.rectangle(round(col * cell), round(row * cell), side, side)
        g.fill()

    return ("field", bg, accent, round(cell, 3)), grid


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
    geom = field_geom(width, height, deck)
    key, grid = field_grid_draw(geom, palette)
    _cached_grid(cr, key, width, height, grid)
    dim, mid, lit = field_tones(palette)
    cells = field_cells(geom, height, mode, state, t)
    buckets: dict = {}
    for color, rects in zip((dim, mid, lit), cells):
        buckets.setdefault(color, []).extend(rects)  # a theme may give two tones one colour
    _fill_buckets(cr, buckets)
