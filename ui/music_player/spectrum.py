from __future__ import annotations

LOOKS = ("blocks", "mirror")


def cycle_look(current: str) -> str:
    if current not in LOOKS:
        return LOOKS[0]
    return LOOKS[(LOOKS.index(current) + 1) % len(LOOKS)]


def bar_index_at(x: float, width: float, count: int) -> int:
    if count <= 0 or width <= 0:
        return 0
    idx = int(float(x) / float(width) * count)
    if idx < 0:
        return 0
    if idx >= count:
        return count - 1
    return idx


def interpolate_bars(bands: list[float], count: int = 36) -> list[float]:
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
