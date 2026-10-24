"""Pure visualizer logic: modes, smoothing, peaks, and per-cell field response.

No GTK or Cairo here so it is cheap to test and shared by the widgets and the
offscreen preview renderer (tools/vis_preview.py).
"""

from __future__ import annotations

import math
from collections import deque

BRICK_COLS = 48
BRICK_SEGS = 12
FIELD_COLS = 81
CLEAR_REACH = 240.0
CLEAR_CURVE = 3.0
SPECTRUM_FLOOR = 0.08
VIS_MODES = ("bricks", "wave", "waterfall")
# Older config values that should still land somewhere sensible.
VIS_ALIASES = {"orbit": "waterfall", "spectrogram": "waterfall"}

BAND_COUNT = 10
BAND_INTERVAL = 0.08  # the window polls the engine for bands every 80 ms

# Bricks: fast attack, slower release; caps hold, then fall with gravity.
BRICK_ATTACK = 0.025
BRICK_RELEASE = 0.20
PEAK_HOLD = 0.38
PEAK_GRAVITY = 1.7

# Wave: a mirrored dot line with a short dim trail.
WAVE_ROWS = 20
WAVE_ATTACK = 0.05
WAVE_RELEASE = 0.24
WAVE_TRAIL = 3

# Waterfall: one LCD column per band update, newest on the right.
WATERFALL_ROWS = BAND_COUNT
WATERFALL_KEEP = 480
WATERFALL_STEPS = 10

# Field: smoothed per update so cells never strobe.
FIELD_ATTACK = 0.06
FIELD_RELEASE = 0.38
FIELD_SLOW_ATTACK = 0.28
FIELD_SLOW_RELEASE = 0.95
FIELD_DRIFT_EVERY = 2  # band updates per field-waterfall ring step
FIELD_KEEP = 200

QUIET_GATE = 0.06

# The engine maps -70..0 dB to 0..1, so real music sits around 0.4-0.8 with
# little swing. A slow per-band floor (falls fast, rises slowly) is subtracted
# so kicks and notes read against the bed; a quiet passage stays low because
# the floor never fully cancels it.
CONTRAST_RISE = 2.5
CONTRAST_FALL = 1.4
CONTRAST_MAX = 0.65
CONTRAST_KEEP = 0.92
CONTRAST_GAIN = 1.25


# ---------------------------------------------------------------- modes


def normalize_vis(mode: object) -> str:
    """Known mode, an old alias (orbit -> waterfall), or the first mode."""
    name = str(mode or "").strip().lower()
    name = VIS_ALIASES.get(name, name)
    return name if name in VIS_MODES else VIS_MODES[0]


def cycle_vis(mode: str) -> str:
    name = VIS_ALIASES.get(str(mode or "").strip().lower(), str(mode or "").strip().lower())
    if name not in VIS_MODES:
        return VIS_MODES[0]
    return VIS_MODES[(VIS_MODES.index(name) + 1) % len(VIS_MODES)]


# ------------------------------------------------------------ smoothing


def clamp01(value: float) -> float:
    return 0.0 if value <= 0.0 else 1.0 if value >= 1.0 else float(value)


def clean_bands(bands: list[float] | None, count: int = BAND_COUNT) -> list[float]:
    vals = [clamp01(float(x)) for x in (bands or [])[:count]]
    while len(vals) < count:
        vals.append(0.0)
    return vals


def ease_levels(
    prev: list[float],
    target: list[float],
    dt: float,
    attack: float,
    release: float,
) -> list[float]:
    """Frame-rate independent one-pole smoothing: rise with `attack`, fall with `release` (seconds)."""
    n = len(target)
    if len(prev) != n:
        prev = list(prev[:n]) + [0.0] * max(0, n - len(prev))
    dt = max(0.0, float(dt))
    k_up = 1.0 if attack <= 0 else 1.0 - math.exp(-dt / attack)
    k_dn = 1.0 if release <= 0 else 1.0 - math.exp(-dt / release)
    out: list[float] = []
    for p, t in zip(prev, target):
        k = k_up if t > p else k_dn
        v = p + (t - p) * k
        out.append(0.0 if v < 1e-4 else v)
    return out


def gate(level: float, floor: float = QUIET_GATE, curve: float = 1.25) -> float:
    """Soft noise gate: nothing below `floor`, and a gentle curve keeps quiet music quiet."""
    if level <= floor:
        return 0.0
    v = clamp01((level - floor) / (1.0 - floor))
    return v**curve


def fall_peaks(
    peaks: list[float],
    holds: list[float],
    vels: list[float],
    bars: list[float],
    dt: float,
    hold: float = PEAK_HOLD,
    gravity: float = PEAK_GRAVITY,
) -> tuple[list[float], list[float], list[float]]:
    """Peak caps: jump to a new high, hold for `hold` seconds, then fall with gravity."""
    n = len(bars)

    def fit(xs: list[float]) -> list[float]:
        return list(xs[:n]) + [0.0] * max(0, n - len(xs))

    peaks, holds, vels = fit(peaks), fit(holds), fit(vels)
    out_p: list[float] = []
    out_h: list[float] = []
    out_v: list[float] = []
    for p, h, v, bar in zip(peaks, holds, vels, bars):
        if bar >= p:
            out_p.append(float(bar))
            out_h.append(hold)
            out_v.append(0.0)
            continue
        if h > 0:
            out_p.append(p)
            out_h.append(max(0.0, h - dt))
            out_v.append(0.0)
            continue
        v = v + gravity * dt
        p = max(float(bar), p - v * dt)
        out_p.append(0.0 if p < 1e-3 else p)
        out_h.append(0.0)
        out_v.append(v)
    return out_p, out_h, out_v


# --------------------------------------------------------- band shaping


def interpolate_bars(bands: list[float], count: int = BRICK_COLS) -> list[float]:
    if count <= 0:
        return []
    if not bands:
        return [0.0] * count
    if len(bands) == 1:
        return [clamp01(float(bands[0]))] * count
    if count == 1:
        return [clamp01(float(bands[0]))]
    out: list[float] = []
    last = len(bands) - 1
    for i in range(count):
        pos = i * last / (count - 1)
        lo = int(pos)
        hi = min(last, lo + 1)
        frac = pos - lo
        val = float(bands[lo]) * (1.0 - frac) + float(bands[hi]) * frac
        out.append(clamp01(val))
    return out


def interpolate_smooth(bands: list[float], count: int) -> list[float]:
    """Catmull-Rom through the bands, so a dot line reads as one calm curve."""
    if count <= 0:
        return []
    if not bands:
        return [0.0] * count
    if len(bands) == 1 or count == 1:
        return [clamp01(float(bands[0]))] * count
    pts = [float(b) for b in bands]
    last = len(pts) - 1
    out: list[float] = []
    for i in range(count):
        pos = i * last / (count - 1)
        k = min(last - 1, int(pos))
        f = pos - k
        p0 = pts[max(0, k - 1)]
        p1 = pts[k]
        p2 = pts[k + 1]
        p3 = pts[min(last, k + 2)]
        f2 = f * f
        v = 0.5 * (2 * p1 + (p2 - p0) * f + (2 * p0 - 5 * p1 + 4 * p2 - p3) * f2 + (3 * p1 - p0 - 3 * p2 + p3) * f2 * f)
        out.append(clamp01(v))
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


def wave_row(level: float, half_rows: int) -> int:
    """Rows away from the center line for one wave column (0 = resting on the line)."""
    if half_rows <= 1:
        return 0
    v = gate(level, 0.04, 0.7)
    return max(0, min(half_rows - 1, int(round(v * (half_rows - 1)))))


def waterfall_step(level: float, steps: int = WATERFALL_STEPS) -> int:
    """Brightness step for one spectrogram cell; 0 means unlit."""
    v = gate(level, 0.18, 1.3)
    return max(0, min(steps, int(math.ceil(v * steps - 0.15))))


def push_history(history: deque, frame: list[float]) -> deque:
    history.append(list(frame))
    return history


# ---------------------------------------------------------------- field


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


def band_at_height(cy: float, height: float, bands: list[float]) -> float:
    """Spectrogram rows: bass at the bottom of the screen, treble at the top."""
    n = len(bands)
    if n == 0 or height <= 0:
        return 0.0
    pos = (1.0 - clamp01(float(cy) / float(height))) * n - 0.5
    b0 = max(0, min(n - 1, int(math.floor(pos))))
    b1 = min(n - 1, b0 + 1)
    f = clamp01(pos - b0)
    return float(bands[b0]) * (1.0 - f) + float(bands[b1]) * f


def bass_of(bands: list[float]) -> float:
    if not bands:
        return 0.0
    low = bands[:3]
    return sum(low) / len(low)


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
    ring: float = 0.0,
    history: deque | list | None = None,
) -> float:
    """0..1 extra light for one field cell.

    bricks: bass columns rise from the floor at the outer edges, treble near the deck.
    wave: a slow horizon swell on the deck's center line, pushed out from the edges by bass.
    waterfall: past spectra drift outward from the deck in square rings (y is frequency).
    `ring` is the cell's distance outside the deck rectangle, in px.
    """
    if cell <= 0:
        return 0.0
    if mode == "wave":
        side = clamp01(abs(cx - mid_x) / max(1.0, half))
        reach = clamp01((side - 0.22) / 0.78) ** 0.9
        d = abs(cy - mid_y)
        line = 0.12 * reach if d < cell * 0.5 else 0.0
        swell = gate(bass_of(bands), 0.04, 1.1)
        if swell <= 0 or reach <= 0:
            return line
        undulate = 0.9 + 0.1 * math.sin(t * 0.5 + side * 2.2)
        thick = cell * 0.5 + swell * reach * height * 0.30 * undulate
        if d >= thick:
            return line
        glow = (0.45 + 0.55 * swell) * (0.4 + 0.6 * reach) * (1.0 - d / thick) ** 1.2
        return max(line, glow)
    if mode == "waterfall":
        if not history:
            return 0.0
        n = len(history)
        age = int(ring / cell)
        if age >= n:
            return 0.0
        frame = history[n - 1 - age]
        level = gate(band_at_height(cy, height, frame), 0.15, 1.2)
        if level <= 0:
            return 0.0
        fade = max(0.0, 1.0 - ring / max(1.0, half))
        return min(1.0, level * 1.3 * (0.25 + 0.75 * fade**1.4))
    level = gate(field_band_at(cx, mid_x, half, bands), 0.02, 1.25)
    if level <= 0:
        return 0.0
    up = (height - cy) / cell
    tall = level * (height / cell) * 0.85
    if 0 <= up < tall:
        return level * (1 - up / tall) ** 0.85
    return 0.0


def field_clearance(dx: float, dy: float, reach: float = CLEAR_REACH) -> float:
    if dx <= 0 and dy <= 0:
        return 0.0
    shade = min(1.0, (dx * dx + dy * dy) ** 0.5 / reach)
    return shade**CLEAR_CURVE


# ---------------------------------------------------------------- state


def contrast_bands(bands: list[float], floor: list[float]) -> list[float]:
    """Subtract most of a per-band running floor and rescale back to 0..1."""
    out: list[float] = []
    for v, f in zip(bands, floor):
        f = min(CONTRAST_MAX, max(0.0, float(f))) * CONTRAST_KEEP
        out.append(clamp01((float(v) - f) / (1.0 - f) * CONTRAST_GAIN))
    return out


class Contrast:
    def __init__(self) -> None:
        self.floor = [0.0] * BAND_COUNT

    def apply(self, bands: list[float] | None, dt: float = BAND_INTERVAL) -> list[float]:
        vals = clean_bands(bands)
        self.floor = ease_levels(self.floor, vals, dt, CONTRAST_RISE, CONTRAST_FALL)
        return contrast_bands(vals, self.floor)


class LcdState:
    """Animation state for the LCD strip. `set_bands` at engine rate, `advance` per frame."""

    def __init__(self) -> None:
        self.target = [0.0] * BAND_COUNT
        self.level = [0.0] * BAND_COUNT  # bricks smoothing
        self.wave = [0.0] * BAND_COUNT  # wave smoothing
        self.bars = [0.0] * BRICK_COLS
        self.peaks = [0.0] * BRICK_COLS
        self._holds = [0.0] * BRICK_COLS
        self._vels = [0.0] * BRICK_COLS
        self.trail: deque = deque(maxlen=WAVE_TRAIL)
        self.history: deque = deque(maxlen=WATERFALL_KEEP)
        self._wf = [0.0] * BAND_COUNT
        self.serial = 0  # bumps on every band update
        self._contrast = Contrast()

    def set_bands(self, bands: list[float] | None, dt: float = BAND_INTERVAL) -> None:
        self.target = self._contrast.apply(bands, dt)
        self.trail.appendleft(list(self.wave))
        self._wf = ease_levels(self._wf, self.target, dt, 0.02, 0.10)
        self.history.append(list(self._wf))
        self.serial += 1

    def advance(self, dt: float) -> bool:
        """Step smoothing by dt seconds. True while anything is still visible or moving."""
        dt = max(0.0, min(0.25, float(dt)))
        self.level = ease_levels(self.level, self.target, dt, BRICK_ATTACK, BRICK_RELEASE)
        self.wave = ease_levels(self.wave, self.target, dt, WAVE_ATTACK, WAVE_RELEASE)
        self.bars = interpolate_bars(self.level, BRICK_COLS)
        self.peaks, self._holds, self._vels = fall_peaks(self.peaks, self._holds, self._vels, self.bars, dt)
        return any(v > 1e-3 for v in self.peaks) or any(v > 1e-3 for v in self.wave) or any(
            v > 1e-3 for v in self.target
        )


class FieldState:
    """Smoothed inputs for the background field; updated once per band poll."""

    def __init__(self) -> None:
        self.level = [0.0] * BAND_COUNT
        self.slow = [0.0] * BAND_COUNT
        self.amp = 0.0
        self.history: deque = deque(maxlen=FIELD_KEEP)
        self._tick = 0
        self._contrast = Contrast()

    def set_bands(self, bands: list[float] | None, dt: float = BAND_INTERVAL) -> None:
        vals = self._contrast.apply(bands, dt)
        self.level = ease_levels(self.level, vals, dt, FIELD_ATTACK, FIELD_RELEASE)
        self.slow = ease_levels(self.slow, vals, dt, FIELD_SLOW_ATTACK, FIELD_SLOW_RELEASE)
        mean = sum(vals) / float(BAND_COUNT)
        self.amp = self.amp * 0.9 + mean * 0.1
        self._tick += 1
        if self._tick % FIELD_DRIFT_EVERY == 0 or not self.history:
            self.history.append(list(self.level))

    def bands_for(self, mode: str) -> list[float]:
        return self.slow if mode == "wave" else self.level
