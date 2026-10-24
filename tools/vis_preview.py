#!/usr/bin/python3
"""Render offscreen preview GIFs of every visualizer look, no GTK window.

Uses the real painters (music_player.widgets.vis_paint) on Cairo ImageSurfaces,
driven by synthetic band data polled at the app's real 80 ms rate.

    /usr/bin/python3 tools/vis_preview.py [--out /tmp/vis-lab] [--modes bricks,wave,waterfall]
"""

from __future__ import annotations

import argparse
import math
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ui"))

import cairo  # noqa: E402

from music_player.spectrum import BAND_INTERVAL, VIS_MODES, FieldState, LcdState  # noqa: E402
from music_player.theme import load_active_palette  # noqa: E402
from music_player.widgets.vis_paint import paint_field, paint_lcd, rgb  # noqa: E402

FPS = 30
SECONDS = 5.6
PREROLL = 18.0  # settle the contrast floor and fill the waterfall first
QUIET_FROM, QUIET_TO = PREROLL + 2.6, PREROLL + 4.0
LCD_W, LCD_H = 1136, 84
# The user's monitor is 3840x1600; the deck is 1180x800 and centered.
SCREEN_W, SCREEN_H = 3840, 1600
DECK_W, DECK_H = 1180, 800
FIELD_SCALE = 1 / 3  # -> 1280x533


def synth_bands(t: float, rng: random.Random) -> list[float]:
    """Engine-like bands (-70..0 dB mapped to 0..1, so music sits around 0.4-0.8).

    A kick on the beat in the lows, offbeat hats in the highs, a sustained mid
    melody that moves every two beats, and a quiet breakdown (about -20 dB, no drums).
    """
    bpm = 118.0
    beat = 60.0 / bpm
    kick = math.exp(-(t % beat) / 0.10)
    eighth = beat / 2
    hat = math.exp(-((t - eighth) % beat) / 0.04) if t >= eighth else 0.0
    notes = [4.0, 5.0, 4.5, 6.0, 5.5, 4.0, 3.5, 5.0]
    note = notes[int(t / (beat * 2)) % len(notes)]
    vib = 0.12 * math.sin(t * 5.5)
    quiet = QUIET_FROM <= t < QUIET_TO
    drums = 0.0 if quiet else 1.0
    if QUIET_TO <= t < QUIET_TO + 0.35:
        drums = (t - QUIET_TO) / 0.35
    duck = 0.27 if quiet else 0.0  # ~ -19 dB
    out: list[float] = []
    for b in range(10):
        bed = 0.52 - 0.012 * b  # a pinkish music bed
        v = bed + 0.025 * (rng.random() - 0.5)
        v += drums * kick * (0.34, 0.32, 0.22, 0.10, 0.04, 0, 0, 0, 0, 0)[b]
        v += drums * hat * (0, 0, 0, 0, 0, 0.03, 0.08, 0.20, 0.26, 0.22)[b]
        v += 0.20 * math.exp(-((b - note - vib) ** 2) / 1.4)
        v += 0.07 * math.exp(-((b - (note + 2.5)) ** 2) / 1.0)  # overtone
        v -= duck
        out.append(max(0.0, min(1.0, v)))
    return out


def surf_to_png(surf: cairo.ImageSurface, path: Path) -> None:
    surf.write_to_png(str(path))


def render_mode(mode: str, out: Path, palette) -> tuple[Path, Path]:
    rng = random.Random(7)
    lcd = LcdState()
    field = FieldState()
    frames = int(SECONDS * FPS)
    tmp = Path(tempfile.mkdtemp(prefix=f"vis-{mode}-"))
    lcd_surf = cairo.ImageSurface(cairo.FORMAT_RGB24, LCD_W * 2, LCD_H * 2)
    fw, fh = int(SCREEN_W * FIELD_SCALE), int(SCREEN_H * FIELD_SCALE)
    field_surf = cairo.ImageSurface(cairo.FORMAT_RGB24, fw, fh)
    deck = ((SCREEN_W - DECK_W) / 2, (SCREEN_H - DECK_H) / 2, (SCREEN_W + DECK_W) / 2, (SCREEN_H + DECK_H) / 2)
    dt = 1.0 / FPS
    next_poll = 0.0
    while next_poll < PREROLL:
        bands = synth_bands(next_poll, rng)
        lcd.set_bands(bands)
        field.set_bands(bands)
        for _ in range(round(BAND_INTERVAL * FPS)):
            lcd.advance(BAND_INTERVAL / round(BAND_INTERVAL * FPS))
        next_poll += BAND_INTERVAL
    field_dirty = True
    for i in range(frames):
        t = PREROLL + i * dt
        while t >= next_poll:
            bands = synth_bands(next_poll, rng)
            lcd.set_bands(bands)
            field.set_bands(bands)
            next_poll += BAND_INTERVAL
            field_dirty = True
        lcd.advance(dt)
        cr = cairo.Context(lcd_surf)
        cr.scale(2, 2)
        paint_lcd(cr, LCD_W, LCD_H, mode, palette, lcd)
        surf_to_png(lcd_surf, tmp / f"lcd_{i:04d}.png")
        if field_dirty:  # the app redraws the field once per band poll, not per frame
            cr = cairo.Context(field_surf)
            cr.scale(FIELD_SCALE, FIELD_SCALE)
            paint_field(cr, SCREEN_W, SCREEN_H, deck, mode, palette, field, t)
            # deck blocked out in the bg colour, with a hairline so its edge reads
            l, top, r, b = deck
            cr.set_source_rgb(*rgb(palette.bg))
            cr.rectangle(l, top, r - l, b - top)
            cr.fill()
            cr.set_source_rgb(*rgb(palette.highlight))
            cr.set_line_width(3)
            cr.rectangle(l + 1.5, top + 1.5, r - l - 3, b - top - 3)
            cr.stroke()
            field_dirty = False
        surf_to_png(field_surf, tmp / f"field_{i:04d}.png")
    lcd_gif = out / f"{mode}-lcd.gif"
    field_gif = out / f"{mode}-field.gif"
    for prefix, gif in (("lcd", lcd_gif), ("field", field_gif)):
        subprocess.run(
            [
                "ffmpeg", "-loglevel", "error", "-y", "-framerate", str(FPS),
                "-i", str(tmp / f"{prefix}_%04d.png"),
                "-filter_complex",
                "[0:v]split[a][b];[a]palettegen=max_colors=64:stats_mode=full:reserve_transparent=0[p];"
                "[b][p]paletteuse=dither=none:diff_mode=rectangle",
                "-loop", "0", str(gif),
            ],
            check=True,
        )
    shutil.copy(tmp / f"lcd_{frames // 3:04d}.png", out / f"{mode}-lcd.png")
    shutil.copy(tmp / f"field_{frames // 3:04d}.png", out / f"{mode}-field.png")
    shutil.rmtree(tmp, ignore_errors=True)
    return lcd_gif, field_gif


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/vis-lab")
    ap.add_argument("--modes", default=",".join(VIS_MODES))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    palette = load_active_palette()
    print(f"palette: bg {palette.bg} accent {palette.accent} peak {palette.peak}")
    for mode in [m.strip() for m in args.modes.split(",") if m.strip()]:
        for gif in render_mode(mode, out, palette):
            print(f"{gif}  {gif.stat().st_size / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
