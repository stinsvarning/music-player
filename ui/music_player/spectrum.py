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
VIS_MODES = ("bricks", "wave", "waterfall")  # the looks that draw something
VIS_OFF = "off"  # flat resting grid, no animation, no band analysis
VIS_CYCLE = (*VIS_MODES, VIS_OFF)  # click order
# Older config values that should still land somewhere sensible.
VIS_ALIASES = {"orbit": "waterfall", "spectrogram": "waterfall"}

BAND_COUNT = 10
BAND_INTERVAL = 0.08  # the window polls the engine for bands every 80 ms

# Bricks: fast attack, slower release; caps hold, then fall with gravity.
BRICK_ATTACK = 0.012
BRICK_RELEASE = 0.15
BRICK_PIVOT = 0.40  # bricks expand the calm level around this point...
BRICK_RANGE = 1.6  # ...by this much
BRICK_KICK = 0.45  # and add this much of each hit on top
PEAK_HOLD = 0.24
PEAK_GRAVITY = 2.8

# Wave: a mirrored dot line with a short dim trail.
WAVE_ROWS = 14
WAVE_ATTACK = 0.03
WAVE_RELEASE = 0.17
WAVE_TRAIL = 2
WAVE_PIVOT = 0.40  # like bricks: expand the calm level around this point
WAVE_RANGE = 1.8
WAVE_KICK = 0.50
WAVE_TRAVEL = 2.2  # rad/s of the gentle travelling ripple
WAVE_RIPPLE = 1.5  # ripple height in rows at full energy
WAVE_CYCLES = 1.6  # ripple cycles across the strip
WAVE_ENERGY_GAIN = 2.2  # typical music energy (~0.4) gives a full ripple

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

# Field punch: bricks columns and the wave glow use the strip's trick (expand the
# calm level around a pivot and add each hit) so they climb and pulse with the beat.
# Bricks columns follow each band against its own recent level (so a bass-light
# track still climbs) with each hit kicked on top.
FIELD_BRICK_BASE = 0.36
FIELD_BRICK_RANGE = 1.6
FIELD_BRICK_KICK = 1.2
FIELD_BRICK_MEAN_TAU = 2.5
FIELD_BRICK_TALL = 0.45  # column height at full level, as a share of the screen height
FIELD_WAVE_PIVOT = 0.30
FIELD_WAVE_RANGE = 1.8
FIELD_WAVE_KICK = 0.9
FIELD_WAVE_ATTACK = 0.05
FIELD_WAVE_RELEASE = 0.30

QUIET_GATE = 0.06

# Volume: the app's slider (0-100) scales every look. A perceptual curve with a
# floor keeps the visuals readable at low volume.
VOLUME_FLOOR = 0.25
VOLUME_CURVE = 0.7

# Redraw cap for the per-frame strip animation, whatever the monitor's refresh.
MAX_FPS = 60.0

# The engine reports per-band RMS over 80 ms, mapped from -70..0 dB to 0..1.
# Measured on real (loud, compressed) music the bands sit at 0.45-0.8 and move
# only about +-0.03 (sd) per band, so a fixed floor either shows a flat wall or
# nothing. Dynamics normalises each band against its own running mean and
# spread, keeps a little of the spectral tilt, and scales everything by overall
# loudness so a quiet track stays quiet.
DYN_MEAN_TAU = 2.0
DYN_DEV_TAU = 2.0
DYN_DEV_FLOOR = 0.012
DYN_BASE = 0.38
DYN_SHAPE = 0.7
DYN_SWING = 0.16
DYN_EVENT_FROM = 0.7  # z above which a band "hits" (waterfall)
DYN_EVENT_SPAN = 2.3
DYN_LOUD_FROM = 0.22  # mean raw band level that counts as silence
DYN_LOUD_SPAN = 0.36  # ... and how much more is full loudness


# ---------------------------------------------------------------- modes


def volume_intensity(volume: float | None) -> float:
    """0-100 volume -> 0.25..1 visual intensity (1 at full volume)."""
    if volume is None:
        return 1.0
    try:
        v = clamp01(float(volume) / 100.0)
    except (TypeError, ValueError):
        return 1.0
    return VOLUME_FLOOR + (1.0 - VOLUME_FLOOR) * v**VOLUME_CURVE


def expand(value: float, event: float, pivot: float, span: float, kick: float) -> float:
    """Stretch a calm level around `pivot` and add a share of the hit on top."""
    if value <= 0:
        return 0.0
    return clamp01(pivot + (value - pivot) * span + kick * event)


class FramePacer:
    """Caps per-frame work at `fps` on any refresh rate, without drifting.

    `step(dt)` takes the frame-clock delta and returns the time to advance by
    when this frame should draw, or None to skip it.
    """

    def __init__(self, fps: float = MAX_FPS) -> None:
        self.period = 1.0 / fps
        self.credit = 0.0
        self.elapsed = 0.0

    def step(self, dt: float) -> float | None:
        dt = max(0.0, float(dt))
        self.credit += dt
        self.elapsed += dt
        if self.credit + 0.0015 < self.period:  # small slack for clock jitter
            return None
        self.credit = min(self.period, self.credit - self.period)  # may dip below 0 by the slack, so it averages out
        out, self.elapsed = self.elapsed, 0.0
        return out

    def reset(self) -> None:
        self.credit = self.period  # draw the first frame after waking
        self.elapsed = 0.0


def vis_name(mode: object) -> str | None:
    """A known setting (a look or off, old aliases mapped), or None."""
    name = str(mode or "").strip().lower()
    name = VIS_ALIASES.get(name, name)
    return name if name in VIS_CYCLE else None


def normalize_vis(mode: object) -> str:
    """Known setting, an old alias (orbit -> waterfall), or the first look."""
    return vis_name(mode) or VIS_MODES[0]


def cycle_vis(mode: str) -> str:
    """bricks -> wave -> waterfall -> off -> bricks."""
    name = vis_name(mode)
    if name is None:
        return VIS_MODES[0]
    return VIS_CYCLE[(VIS_CYCLE.index(name) + 1) % len(VIS_CYCLE)]


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
    for k, f, f2 in _smooth_steps(last, count):
        p0 = pts[k - 1 if k > 0 else 0]
        p1 = pts[k]
        p2 = pts[k + 1]
        p3 = pts[k + 2 if k + 2 < last else last]
        v = 0.5 * (2 * p1 + (p2 - p0) * f + (2 * p0 - 5 * p1 + 4 * p2 - p3) * f2 + (3 * p1 - p0 - 3 * p2 + p3) * f2 * f)
        out.append(0.0 if v <= 0.0 else 1.0 if v >= 1.0 else v)
    return out


_SMOOTH_STEPS: dict[tuple[int, int], tuple] = {}


def _smooth_steps(last: int, count: int) -> tuple:
    """(segment, f, f*f) per output point; the same for every frame of a given width."""
    key = (last, count)
    hit = _SMOOTH_STEPS.get(key)
    if hit is None:
        steps = []
        for i in range(count):
            pos = i * last / (count - 1)
            k = min(last - 1, int(pos))
            f = pos - k
            steps.append((k, f, f * f))
        hit = _SMOOTH_STEPS[key] = tuple(steps)
    return hit


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


def wave_heights(levels: list[float], cols: int, half_rows: int, phase: float = 0.0, energy: float = 0.0) -> list[float]:
    """Fractional rows above the centre line for each wave column.

    Bands are eased into a curve, and a gentle ripple scaled by the music's
    energy travels along it so the line keeps moving on sustained sounds.
    Silence gives a flat line at 0.
    """
    if cols <= 0:
        return []
    top = max(0.0, float(half_rows - 1))
    curve = interpolate_smooth(levels, cols)
    swell = WAVE_RIPPLE * clamp01(energy * WAVE_ENERGY_GAIN)
    out: list[float] = []
    # gate(v, 0.03, 0.75) inlined: this runs for every column on every frame
    span = 1.0 - 0.03
    angles = _ripple_angles(cols) if swell > 0 else None
    for c, v in enumerate(curve):
        if v <= 0.03:
            h = 0.0 * top
        else:
            g = (v - 0.03) / span
            h = (0.0 if g <= 0.0 else 1.0 if g >= 1.0 else g) ** 0.75 * top
        if angles is not None:
            h += swell * math.sin(angles[c] - phase) * min(1.0, 0.35 + h / 2)
        out.append(0.0 if h <= 0.0 else top if h >= top else h)
    return out


_RIPPLE_ANGLES: dict[int, tuple[float, ...]] = {}


def _ripple_angles(cols: int) -> tuple[float, ...]:
    hit = _RIPPLE_ANGLES.get(cols)
    if hit is None:
        hit = _RIPPLE_ANGLES[cols] = tuple(math.tau * WAVE_CYCLES * c / max(1, cols) for c in range(cols))
    return hit


def waterfall_step(level: float, steps: int = WATERFALL_STEPS) -> int:
    """Brightness step for one spectrogram cell; 0 means unlit."""
    v = gate(level, 0.10, 1.1)
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
        swell = gate(bass_of(bands), 0.04, 1.1)
        if swell <= 0 or reach <= 0:
            return 0.0  # dark at rest
        line = 0.16 * reach * min(1.0, swell * 4.0) if d < cell * 0.5 else 0.0
        undulate = 0.9 + 0.1 * math.sin(t * 0.5 + side * 2.2)
        thick = cell * 0.5 + swell * reach * height * 0.36 * undulate
        if d >= thick:
            return line
        glow = min(1.0, (0.55 + 0.75 * swell) * (0.45 + 0.55 * reach)) * (1.0 - d / thick) ** 0.9
        return max(line, glow)
    if mode == "waterfall":
        if not history:
            return 0.0
        n = len(history)
        age = int(ring / cell)
        if age >= n:
            return 0.0
        frame = history[n - 1 - age]
        level = gate(band_at_height(cy, height, frame), 0.10, 1.1)
        if level <= 0:
            return 0.0
        fade = max(0.0, 1.0 - ring / max(1.0, half))
        return min(1.0, level * 1.3 * (0.25 + 0.75 * fade**1.4))
    level = gate(field_band_at(cx, mid_x, half, bands), 0.02, 1.25)
    if level <= 0:
        return 0.0
    up = (height - cy) / cell
    tall = level * (height / cell) * FIELD_BRICK_TALL
    if 0 <= up < tall:
        return min(1.0, level * (0.45 + 0.55 * (1 - up / tall) ** 0.7) * 1.25)
    return 0.0


def field_clearance(dx: float, dy: float, reach: float = CLEAR_REACH) -> float:
    if dx <= 0 and dy <= 0:
        return 0.0
    shade = min(1.0, (dx * dx + dy * dy) ** 0.5 / reach)
    return shade**CLEAR_CURVE


# ---------------------------------------------------------------- state


def band_z(value: float, mean: float, dev: float) -> float:
    """How unusual this band is right now, in units of its own recent spread."""
    z = (float(value) - float(mean)) / max(DYN_DEV_FLOOR, float(dev) * 1.25)
    return max(-2.5, min(3.5, z))


def loudness(bands: list[float]) -> float:
    if not bands:
        return 0.0
    return clamp01((sum(bands) / len(bands) - DYN_LOUD_FROM) / DYN_LOUD_SPAN)


class Dynamics:
    """Raw engine bands -> (level, events), both 0..1 per band.

    level: a calm spectrum for bars and lines (base + a little tilt + swing).
    events: only the moments a band rises clearly above its recent norm.
    """

    def __init__(self) -> None:
        self.mean: list[float] | None = None
        self.dev = [0.03] * BAND_COUNT
        self.loud = 0.0

    def apply(self, bands: list[float] | None, dt: float = BAND_INTERVAL) -> tuple[list[float], list[float]]:
        vals = clean_bands(bands)
        if not any(vals):
            self.loud = ease_levels([self.loud], [0.0], dt, 0.15, 0.35)[0]
            return [0.0] * BAND_COUNT, [0.0] * BAND_COUNT
        if self.mean is None or not any(self.mean):
            self.mean = list(vals)
        self.mean = ease_levels(self.mean, vals, dt, DYN_MEAN_TAU, DYN_MEAN_TAU)
        spread = [abs(v - m) for v, m in zip(vals, self.mean)]
        self.dev = ease_levels(self.dev, spread, dt, DYN_DEV_TAU, DYN_DEV_TAU)
        self.loud = ease_levels([self.loud], [loudness(vals)], dt, 0.15, 0.5)[0]
        tilt = sum(self.mean) / BAND_COUNT
        level: list[float] = []
        events: list[float] = []
        for v, m, d in zip(vals, self.mean, self.dev):
            z = band_z(v, m, d)
            level.append(self.loud * clamp01(DYN_BASE + (m - tilt) * DYN_SHAPE + DYN_SWING * z))
            events.append(self.loud * clamp01((z - DYN_EVENT_FROM) / DYN_EVENT_SPAN))
        return level, events


class LcdState:
    """Animation state for the LCD strip. `set_bands` at engine rate, `advance` per frame."""

    def __init__(self) -> None:
        self.target = [0.0] * BAND_COUNT
        self.level = [0.0] * BAND_COUNT  # bricks smoothing
        self.wave = [0.0] * BAND_COUNT  # wave smoothing
        self.punch = [0.0] * BAND_COUNT  # bricks target: wider range plus hits
        self.wave_target = [0.0] * BAND_COUNT
        self.phase = 0.0
        self.energy = 0.0
        self.bars = [0.0] * BRICK_COLS
        self.peaks = [0.0] * BRICK_COLS
        self.peak_holds = [0.0] * BRICK_COLS  # >0 while a cap is freshly holding
        self._vels = [0.0] * BRICK_COLS
        self.trail: deque = deque(maxlen=WAVE_TRAIL)
        self.history: deque = deque(maxlen=WATERFALL_KEEP)
        self._wf = [0.0] * BAND_COUNT
        self.serial = 0  # bumps on every band update
        self._trail_dots = None  # the painter's cache of the trail lines, keyed by serial
        self.intensity = 1.0  # from the volume slider, see volume_intensity
        self._dyn = Dynamics()

    def set_volume(self, volume: float | None) -> None:
        self.intensity = volume_intensity(volume)

    def set_bands(self, bands: list[float] | None, dt: float = BAND_INTERVAL) -> None:
        self.target, events = self._dyn.apply(bands, dt)
        k = self.intensity
        self.punch = [k * expand(v, e, BRICK_PIVOT, BRICK_RANGE, BRICK_KICK) for v, e in zip(self.target, events)]
        self.wave_target = [k * expand(v, e, WAVE_PIVOT, WAVE_RANGE, WAVE_KICK) for v, e in zip(self.target, events)]
        self.trail.appendleft((list(self.wave), self.phase, self.energy))
        self._wf = ease_levels(self._wf, [k * e for e in events], dt, 0.02, 0.12)
        self.history.append(list(self._wf))
        self.serial += 1

    def advance(self, dt: float) -> bool:
        """Step smoothing by dt seconds. True while anything is still visible or moving."""
        dt = max(0.0, min(0.25, float(dt)))
        self.level = ease_levels(self.level, self.punch, dt, BRICK_ATTACK, BRICK_RELEASE)
        self.wave = ease_levels(self.wave, self.wave_target, dt, WAVE_ATTACK, WAVE_RELEASE)
        mean = self.intensity * sum(self.target) / BAND_COUNT
        self.energy = ease_levels([self.energy], [mean], dt, 0.08, 0.6)[0]
        self.phase = (self.phase + WAVE_TRAVEL * dt) % math.tau
        self.bars = interpolate_bars(self.level, BRICK_COLS)
        self.peaks, self.peak_holds, self._vels = fall_peaks(self.peaks, self.peak_holds, self._vels, self.bars, dt)
        return (
            any(v > 1e-3 for v in self.peaks)
            or any(v > 1e-3 for v in self.wave)
            or any(v > 1e-3 for v in self.target)
            or self.energy > 1e-3
        )


class FieldState:
    """Smoothed inputs for the background field; updated once per band poll."""

    def __init__(self) -> None:
        self.level = [0.0] * BAND_COUNT
        self.slow = [0.0] * BAND_COUNT
        self.amp = 0.0
        self.history: deque = deque(maxlen=FIELD_KEEP)
        self._tick = 0
        self._dyn = Dynamics()
        self._events = [0.0] * BAND_COUNT
        self.bricks = [0.0] * BAND_COUNT  # level against its own norm, kicked by hits
        self._brick_mean: list[float] | None = None
        self.wave = [0.0] * BAND_COUNT  # quicker, punchier swell for the wave glow
        self.intensity = 1.0

    def set_volume(self, volume: float | None) -> None:
        self.intensity = volume_intensity(volume)

    def set_bands(self, bands: list[float] | None, dt: float = BAND_INTERVAL) -> None:
        vals, events = self._dyn.apply(bands, dt)
        k = self.intensity
        vals = [k * v for v in vals]
        events = [k * e for e in events]
        self._events = ease_levels(self._events, events, dt, FIELD_ATTACK, FIELD_RELEASE)
        self.level = ease_levels(self.level, vals, dt, FIELD_ATTACK, FIELD_RELEASE)
        self.slow = ease_levels(self.slow, vals, dt, FIELD_SLOW_ATTACK, FIELD_SLOW_RELEASE)
        raw = [v / k for v in self.level]
        if self._brick_mean is None:
            self._brick_mean = list(raw)
        self._brick_mean = ease_levels(self._brick_mean, raw, dt, FIELD_BRICK_MEAN_TAU, FIELD_BRICK_MEAN_TAU)
        self.bricks = [
            k * clamp01(FIELD_BRICK_BASE + (v - m) * FIELD_BRICK_RANGE + FIELD_BRICK_KICK * e / k) if v > 1e-3 else 0.0
            for v, m, e in zip(raw, self._brick_mean, self._events)
        ]
        swell = [
            k * expand(v / k if k else 0.0, e / k if k else 0.0, FIELD_WAVE_PIVOT, FIELD_WAVE_RANGE, FIELD_WAVE_KICK)
            for v, e in zip(vals, events)
        ]
        self.wave = ease_levels(self.wave, swell, dt, FIELD_WAVE_ATTACK, FIELD_WAVE_RELEASE)
        mean = sum(vals) / float(BAND_COUNT)
        self.amp = self.amp * 0.9 + mean * 0.1
        self._tick += 1
        if self._tick % FIELD_DRIFT_EVERY == 0 or not self.history:
            self.history.append(list(self._events))

    def bands_for(self, mode: str) -> list[float]:
        if mode == "wave":
            return self.wave
        if mode == "bricks":
            return self.bricks
        return self.level
