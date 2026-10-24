from __future__ import annotations

import math

BRICK_COLS = 48
BRICK_SEGS = 12
FIELD_COLS = 81
CLEAR_REACH = 240.0
CLEAR_CURVE = 3.0
SPECTRUM_FLOOR = 0.08
VIS_MODES = ("bricks", "wave", "orbit")

# Nested stadium orbits in the LCD. Lane 0 is the outer (bass) rail.
ORBIT_LANES = 3
ORBIT_RAIL = 0.16
# Concentric field rings. 0 is the inner edge of the ring band (toward the deck).
ORBIT_FIELD_RINGS = 7
ORBIT_RING_INNER = 0.40
ORBIT_RING_SPAN = 0.58

_ORBIT_PATHS: dict[tuple[int, int, int], tuple[tuple[int, int], ...]] = {}


def cycle_vis(mode: str) -> str:
    if mode not in VIS_MODES:
        return VIS_MODES[0]
    return VIS_MODES[(VIS_MODES.index(mode) + 1) % len(VIS_MODES)]


def field_level(side: float, bands: list[float]) -> float:
    """side 0 is the deck/center (treble), 1 is the outer edge (bass)."""
    n = len(bands)
    if n == 0:
        return 0.0
    pos = (1.0 - min(1.0, max(0.0, float(side)))) * n - 0.5
    b0 = max(0, min(n - 1, int(pos)))
    b1 = min(n - 1, b0 + 1)
    mix_b = max(0.0, min(1.0, pos - b0))
    raw = float(bands[b0]) * (1.0 - mix_b) + float(bands[b1]) * mix_b
    return max(0.0, (raw - SPECTRUM_FLOOR) / (1.0 - SPECTRUM_FLOOR))


def field_band_at(cx: float, mid_x: float, half: float, bands: list[float]) -> float:
    """Bass lives at the outer edges; treble toward the centered deck."""
    if half <= 0:
        return 0.0
    return field_level(abs(float(cx) - float(mid_x)) / float(half), bands)


def orbit_ring_r(index: int, rings: int = ORBIT_FIELD_RINGS) -> float:
    """Normalized radius of a field-ring centerline. 0 is the deck, 1 the edge."""
    if rings <= 0:
        return 0.0
    step = ORBIT_RING_SPAN / rings
    return ORBIT_RING_INNER + (index + 0.5) * step


def _bricks_field(
    cx: float,
    cy: float,
    mid_x: float,
    half: float,
    height: float,
    cell: float,
    bands: list[float],
) -> float:
    """Floor-anchored columns. A one-cell gap lifts the cap off the body."""
    if cell <= 0.0 or height <= 0.0:
        return 0.0
    level = field_band_at(cx, mid_x, half, bands)
    if level <= 0.02:
        return 0.0
    up = (height - cy) / cell
    tall = level * (height / cell) * 0.90
    if up < 0.0 or up >= tall:
        return 0.0
    if tall < 3.2:
        return 0.9
    if up >= tall - 1.15:
        return 1.0
    if up >= tall - 2.4:
        return 0.0
    return 0.88


def _wave_field(
    cx: float,
    cy: float,
    mid_x: float,
    mid_y: float,
    half: float,
    cell: float,
    bands: list[float],
    t: float,
) -> float:
    """Crests travel outward from the deck. Bass still owns the outer edge."""
    if half <= 0.0 or cell <= 0.0:
        return 0.0
    side = min(1.0, abs(cx - mid_x) / half)
    level = field_level(side, bands)
    if level <= 0.0:
        return 0.0
    outward = abs(cx - mid_x) / cell
    y = (cy - mid_y) / cell
    phase = outward * 0.40 - t * 2.25 + math.sin(y * 0.34) * 1.15
    crest = math.cos(phase)
    if crest <= 0.0:
        return 0.0
    ridge = crest * crest * crest
    if ridge > 0.55 and level > 0.28:
        return min(1.0, 0.82 + 0.18 * level)
    return min(1.0, level * ridge)


def _orbit_field(
    cx: float,
    cy: float,
    mid_x: float,
    mid_y: float,
    half: float,
    height: float,
    bands: list[float],
    t: float,
) -> float:
    """Concentric rings. The hot side of each ring is thicker, and inner rings spin faster."""
    if half <= 0.0:
        return 0.0
    dx = cx - mid_x
    dy = cy - mid_y
    dist = math.hypot(dx, dy)
    reach = max(half, height * 0.5)
    if reach <= 0.0:
        return 0.0
    rings = ORBIT_FIELD_RINGS
    step = ORBIT_RING_SPAN / rings
    slot = (dist / reach - ORBIT_RING_INNER) / step
    if slot < 0.0 or slot >= rings:
        return 0.0
    idx = int(slot)
    radial = abs(slot - idx - 0.5)
    side = ORBIT_RING_INNER + (idx + 0.5) * step
    level = field_level(side, bands)
    if level <= 0.02:
        return 0.0
    ang = math.atan2(dy, dx)
    lobe = 0.5 + 0.5 * math.cos(ang - t * (1.25 - idx * 0.11))
    half_w = 0.18 + 0.20 * level * (0.42 + 0.58 * lobe)
    if radial >= half_w:
        return 0.0
    edge = 1.0 - radial / half_w
    shape = edge * edge * (3.0 - 2.0 * edge)
    if level >= 0.42 and shape > 0.4:
        return min(1.0, 0.84 + 0.16 * lobe)
    return min(1.0, level * shape * (0.5 + 0.5 * lobe))


def field_spec(
    mode: str,
    *,
    cx: float,
    cy: float,
    mid_x: float,
    mid_y: float,
    half: float,
    height: float,
    cell: float,
    bands: list[float],
    t: float,
) -> float:
    """0..1 extra light for one field cell. Bass stays at the outer edge in every look."""
    if mode == "wave":
        return _wave_field(cx, cy, mid_x, mid_y, half, cell, bands, t)
    if mode == "orbit":
        return _orbit_field(cx, cy, mid_x, mid_y, half, height, bands, t)
    return _bricks_field(cx, cy, mid_x, half, height, cell, bands)


def field_clearance(dx: float, dy: float, reach: float = CLEAR_REACH) -> float:
    if dx <= 0 and dy <= 0:
        return 0.0
    shade = min(1.0, (dx * dx + dy * dy) ** 0.5 / reach)
    return shade**CLEAR_CURVE


def smooth_levels(
    prev: list[float],
    target: list[float],
    dt: float = 1.0 / 30.0,
    *,
    attack: float = 16.0,
    decay: float = 3.2,
) -> list[float]:
    """Asymmetric exponential smoother. Attack is quicker than release."""
    dt = max(0.0, min(0.1, float(dt)))
    attack_k = 1.0 - math.exp(-float(attack) * dt)
    decay_k = 1.0 - math.exp(-float(decay) * dt)
    out: list[float] = []
    nprev = len(prev)
    for i, raw in enumerate(target):
        cur = float(prev[i]) if i < nprev else 0.0
        goal = float(raw)
        if goal < 0.0:
            goal = 0.0
        elif goal > 1.0:
            goal = 1.0
        k = attack_k if goal >= cur else decay_k
        val = cur + (goal - cur) * k
        if val < 0.0:
            val = 0.0
        elif val > 1.0:
            val = 1.0
        out.append(val)
    return out


def interpolate_bars(bands: list[float], count: int = BRICK_COLS) -> list[float]:
    if count <= 0:
        return []
    if not bands:
        return [0.0] * count
    if len(bands) == 1:
        v = max(0.0, min(1.0, float(bands[0])))
        return [v] * count
    out: list[float] = []
    last = len(bands) - 1
    for i in range(count):
        pos = i * last / (count - 1)
        lo = int(pos)
        hi = min(last, lo + 1)
        frac = pos - lo
        val = float(bands[lo]) * (1.0 - frac) + float(bands[hi]) * frac
        out.append(max(0.0, min(1.0, val)))
    return out


def brick_heights(bands: list[float], cols: int = BRICK_COLS, segs: int = BRICK_SEGS) -> list[float]:
    """Fractional column heights in segment units, for a smooth top brick."""
    return [v * segs for v in interpolate_bars(bands, cols)]


def brick_columns(bands: list[float], cols: int = BRICK_COLS, segs: int = BRICK_SEGS) -> list[int]:
    return [max(0, min(segs, int(round(v)))) for v in brick_heights(bands, cols, segs)]


def tick_brick_peaks(peaks: list[int], cols: list[int]) -> list[int]:
    n = len(cols)
    if len(peaks) != n:
        peaks = list(peaks[:n]) + [0] * max(0, n - len(peaks))
    next_peaks: list[int] = []
    for peak, height in zip(peaks, cols):
        if height >= peak:
            next_peaks.append(int(height))
        else:
            next_peaks.append(max(0, int(peak) - 1))
    return next_peaks


def tick_peaks(peaks: list[float], bars: list[float], decay: float = 0.045) -> list[float]:
    n = len(bars)
    if len(peaks) != n:
        peaks = list(peaks[:n]) + [0.0] * max(0, n - len(peaks))
    next_peaks: list[float] = []
    for peak, bar in zip(peaks, bars):
        if bar >= peak:
            next_peaks.append(float(bar))
        else:
            next_peaks.append(max(0.0, float(peak) - decay))
    return next_peaks


def decay_peaks(peaks: list[float], bars: list[float], dt: float, fall: float = 0.55) -> list[float]:
    """Peak-hold with a time-based fall (units per second), so frame rate doesn't change the glide."""
    n = len(bars)
    if len(peaks) != n:
        peaks = list(peaks[:n]) + [0.0] * max(0, n - len(peaks))
    step = max(0.0, float(fall)) * max(0.0, min(0.1, float(dt)))
    out: list[float] = []
    for peak, bar in zip(peaks, bars):
        if bar >= peak:
            out.append(float(bar))
        else:
            out.append(max(0.0, float(peak) - step))
    return out


def wave_reach(col: int, count: int, level: float, t: float) -> float:
    """0..1 half-height of the symmetric traveling waveform at one column."""
    x = 0.0 if count <= 1 else col / (count - 1)
    if level < 0.0:
        level = 0.0
    elif level > 1.0:
        level = 1.0
    fund = math.sin(x * math.tau * 2.5 + t * 2.05)
    harm = math.sin(x * math.tau * 5.5 - t * 3.35)
    shape = 0.56 + 0.44 * (0.74 * fund + 0.26 * harm)
    if shape < 0.0:
        shape = 0.0
    elif shape > 1.0:
        shape = 1.0
    # Loud crests reach the bezel; silence stays a center line.
    reach = shape * (0.08 + 1.08 * level)
    if reach > 1.0:
        return 1.0
    if reach < 0.0:
        return 0.0
    return reach


def orbit_levels(bands: list[float], lanes: int = ORBIT_LANES) -> list[float]:
    """Lane 0 is the outer rail (bass); the last lane sits nearest the center (treble)."""
    if lanes <= 0:
        return []
    if lanes == 1:
        return [field_level(1.0, bands)]
    out: list[float] = []
    last = lanes - 1
    for i in range(lanes):
        out.append(field_level(1.0 - i / last, bands))
    return out


def _lane_edges(segs: int, lane: int) -> tuple[int, int]:
    """Bottom and top segment indexes for one stadium. 0 is the bottom edge."""
    if segs == BRICK_SEGS and ORBIT_LANES == 3:
        # One quiet row between loops, and a two-row eye in the middle.
        edge = (0, 2, 4)[lane] if 0 <= lane < 3 else lane * 2
    else:
        edge = lane * 2
    if edge >= segs // 2:
        edge = max(0, segs // 2 - 1)
    return edge, segs - 1 - edge


def orbit_path(cols: int, segs: int, lane: int) -> tuple[tuple[int, int], ...]:
    """Cached stadium around the LCD. Lane 0 traces the outer edge of the strip."""
    key = (cols, segs, lane)
    hit = _ORBIT_PATHS.get(key)
    if hit is not None:
        return hit
    lanes = ORBIT_LANES if segs >= BRICK_SEGS else max(1, segs // 4)
    if lane < 0 or lane >= lanes or cols < 8 or segs < 6:
        _ORBIT_PATHS[key] = ()
        return _ORBIT_PATHS[key]
    bottom, top = _lane_edges(segs, lane)
    inset = lane * max(3, cols // 12)
    left = inset
    right = cols - 1 - inset
    if right - left < 4 or top <= bottom:
        _ORBIT_PATHS[key] = ()
        return _ORBIT_PATHS[key]
    cells: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()

    def add(c: int, r: int) -> None:
        if c < 0 or r < 0 or c >= cols or r >= segs:
            return
        pair = (c, r)
        if pair in seen:
            return
        seen.add(pair)
        cells.append(pair)

    for c in range(left, right + 1):
        add(c, bottom)
    for r in range(bottom + 1, top):
        add(right, r)
    for c in range(right, left - 1, -1):
        add(c, top)
    for r in range(top - 1, bottom, -1):
        add(left, r)
    path = tuple(cells)
    _ORBIT_PATHS[key] = path
    return path


def orbit_head_index(length: int, lane: int, t: float) -> int:
    """Inner lanes lap faster, and each lane is staggered so the heads don't stack."""
    if length <= 0:
        return 0
    phase = (float(t) * (0.11 + lane * 0.07) + lane * 0.33) % 1.0
    return int(phase * length) % length


def fill_orbit_brightness(
    out: list[float],
    bands: list[float],
    t: float,
    cols: int = BRICK_COLS,
    segs: int = BRICK_SEGS,
) -> None:
    """Write a 0..1 brightness for every LCD cell. `out` is cols*segs, row-major, row 0 at the bottom.

    Quiet rails stay visible so the loops read at rest. A comet trails behind each head.
    """
    n = cols * segs
    if len(out) < n:
        return
    for i in range(n):
        out[i] = 0.0
    lanes = ORBIT_LANES if segs >= BRICK_SEGS else max(1, segs // 4)
    levels = orbit_levels(bands, lanes)
    rail = ORBIT_RAIL
    for lane, level in enumerate(levels):
        path = orbit_path(cols, segs, lane)
        plen = len(path)
        if plen == 0:
            continue
        for c, r in path:
            i = r * cols + c
            if out[i] < rail:
                out[i] = rail
        if level <= 0.04:
            continue
        span = max(1, int(level * plen * 0.62))
        head = orbit_head_index(plen, lane, t)
        for step in range(span):
            c, r = path[(head - step) % plen]
            fade = (1.0 - step / span) ** 0.42
            val = rail + (1.0 - rail) * level * fade
            if step == 0 and level >= 0.18 and val < 0.93:
                val = 0.93
            if val > 1.0:
                val = 1.0
            i = r * cols + c
            if val > out[i]:
                out[i] = val


def bar_index_at(x: float, width: float, count: int) -> int:
    if count <= 0 or width <= 0:
        return 0
    idx = int(float(x) / float(width) * count)
    if idx < 0:
        return 0
    if idx >= count:
        return count - 1
    return idx
