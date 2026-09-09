from __future__ import annotations

import math

BRICK_COLS = 48
BRICK_SEGS = 12
FIELD_COLS = 81
CLEAR_REACH = 240.0
CLEAR_CURVE = 3.0
SPECTRUM_FLOOR = 0.08
VIS_MODES = ("bricks", "wave", "orbit")


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
    """0..1 extra light for one field cell. Same bass-at-edge mapping in every look."""
    if mode == "wave":
        dist = math.hypot(cx - mid_x, cy - mid_y)
        reach = max(half, height * 0.5)
        level = field_level(dist / max(1.0, reach), bands)
        crest = 0.5 + 0.5 * math.sin(dist / max(1.0, cell) * 0.42 - t * 3.4)
        return level * (0.22 + 0.78 * crest * crest)
    if mode == "orbit":
        dx = cx - mid_x
        dy = cy - mid_y
        dist = math.hypot(dx, dy)
        reach = max(half, height * 0.5)
        level = field_level(dist / max(1.0, reach), bands)
        spoke = abs(math.cos((math.atan2(dy, dx) - t * 0.62) * 6.0)) ** 2.4
        return level * (0.18 + 0.82 * spoke)
    level = field_band_at(cx, mid_x, half, bands)
    if level <= 0 or cell <= 0:
        return 0.0
    up = (height - cy) / cell
    tall = level * (height / cell) * 0.92
    if 0 <= up < tall:
        return level * (1 - up / tall) ** 0.85
    return 0.0


def field_clearance(dx: float, dy: float, reach: float = CLEAR_REACH) -> float:
    if dx <= 0 and dy <= 0:
        return 0.0
    shade = min(1.0, (dx * dx + dy * dy) ** 0.5 / reach)
    return shade**CLEAR_CURVE


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


def brick_columns(bands: list[float], cols: int = BRICK_COLS, segs: int = BRICK_SEGS) -> list[int]:
    bars = interpolate_bars(bands, cols)
    return [max(0, min(segs, int(round(v * segs)))) for v in bars]


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


def bar_index_at(x: float, width: float, count: int) -> int:
    if count <= 0 or width <= 0:
        return 0
    idx = int(float(x) / float(width) * count)
    if idx < 0:
        return 0
    if idx >= count:
        return count - 1
    return idx
