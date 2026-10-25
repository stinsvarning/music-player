"""The visualizer's fast paths must draw exactly what the straightforward versions drew."""

import math
import random
import unittest

import cairo

from music_player.spectrum import (
    VIS_MODES,
    FieldState,
    LcdState,
    clamp01,
    field_clearance,
    field_spec,
    gate,
    interpolate_smooth,
    wave_heights,
    WAVE_CYCLES,
    WAVE_ENERGY_GAIN,
    WAVE_RIPPLE,
)
from music_player.theme import FALLBACK, palette_named
from music_player.widgets.vis_paint import (
    BAYER,
    FIELD_COLS,
    FIELD_GAIN,
    FIELD_LIFT,
    JITTER,
    field_cells,
    field_geom,
    paint_lcd,
)


def ref_interpolate_smooth(bands, count):
    """interpolate_smooth before the per-width step cache."""
    if count <= 0:
        return []
    if not bands:
        return [0.0] * count
    if len(bands) == 1 or count == 1:
        return [clamp01(float(bands[0]))] * count
    pts = [float(b) for b in bands]
    last = len(pts) - 1
    out = []
    for i in range(count):
        pos = i * last / (count - 1)
        k = min(last - 1, int(pos))
        f = pos - k
        p0, p1, p2, p3 = pts[max(0, k - 1)], pts[k], pts[k + 1], pts[min(last, k + 2)]
        f2 = f * f
        v = 0.5 * (2 * p1 + (p2 - p0) * f + (2 * p0 - 5 * p1 + 4 * p2 - p3) * f2 + (3 * p1 - p0 - 3 * p2 + p3) * f2 * f)
        out.append(clamp01(v))
    return out


def ref_wave_heights(levels, cols, half_rows, phase=0.0, energy=0.0):
    if cols <= 0:
        return []
    top = max(0.0, float(half_rows - 1))
    curve = ref_interpolate_smooth(levels, cols)
    swell = WAVE_RIPPLE * clamp01(energy * WAVE_ENERGY_GAIN)
    out = []
    for c, v in enumerate(curve):
        h = gate(v, 0.03, 0.75) * top
        if swell > 0:
            h += swell * math.sin(math.tau * WAVE_CYCLES * c / max(1, cols) - phase) * min(1.0, 0.35 + h / 2)
        out.append(max(0.0, min(top, h)))
    return out


def ref_field_cells(width, height, deck, mode, state, t):
    """The per-cell field_spec loop paint_field used to run, as (dim, mid, lit) rect lists."""
    deck_l, deck_t, deck_r, deck_b = deck
    cell = max(4.0, width / FIELD_COLS)
    mid_x = (deck_l + deck_r) / 2 if deck_r > deck_l else width / 2
    mid_y = (deck_t + deck_b) / 2 if deck_b > deck_t else height / 2
    half = max(1.0, width / 2)
    cols = int(math.ceil(width / cell)) + 2
    rows = int(math.ceil(height / cell)) + 2
    side = max(1, round(cell) - 1)
    out = ([], [], [])
    bands = state.bands_for(mode)
    history = state.history if mode == "waterfall" else None
    for col in range(-1, cols):
        x = col * cell
        cx = x + cell / 2
        dx = max(deck_l - cx, 0.0, cx - deck_r) if deck_r > deck_l else 0.0
        for row in range(-1, rows):
            cy0 = row * cell + cell / 2
            dy = max(deck_t - cy0, 0.0, cy0 - deck_b) if deck_b > deck_t else 0.0
            shade = field_clearance(dx, dy)
            if shade < 0.004:
                continue
            y = row * cell
            spec = field_spec(mode, cx=cx, cy=y + cell / 2, mid_x=mid_x, mid_y=mid_y, half=half, height=height,
                              cell=cell, bands=bands, t=t, ring=max(dx, dy), history=history)
            if spec <= 0:
                continue
            energy = (spec * FIELD_GAIN + FIELD_LIFT * min(1.0, spec / 0.08)) * min(1.0, shade * 3)
            j = JITTER[(row * 37 + col * 11) & 4095]
            threshold = 0.78 * ((BAYER[(row & 7) * 8 + (col & 7)] + 0.5) / 64) + 0.22 * j
            if energy <= threshold:
                continue
            heat = spec * (0.66 if mode in ("bricks", "wave") else 0.6)
            k = 2 if heat > 0.34 else 1 if heat > 0.1 else 0
            out[k].append((round(x), round(y), side, side))
    return out


def music(rng, n):
    """Engine-like band polls: a loud bed with hits, a quiet stretch, then silence."""
    rows = []
    for i in range(n):
        loud = 0.0 if i > n - 15 else (0.25 if n // 2 < i < n // 2 + 20 else 1.0)
        rows.append([max(0.0, min(1.0, loud * (0.5 + 0.25 * rng.random() + (0.3 if i % 6 == 0 and b < 3 else 0.0)))) for b in range(10)])
    return rows


class FieldFastPathTests(unittest.TestCase):
    def test_lit_cells_match_the_per_cell_loop(self):
        rng = random.Random(3)
        sizes = [(3836, 1570, (1328.0, 385.0, 2508.0, 1185.0)), (1916, 1570, (368.0, 385.0, 1548.0, 1185.0)), (900, 640, (200.0, 100.0, 700.0, 540.0)), (640, 360, (0.0, 0.0, 0.0, 0.0))]
        for mode in VIS_MODES:
            state = FieldState()
            state.set_volume(70)
            checked = 0
            for i, bands in enumerate(music(rng, 140)):
                state.set_bands(bands)
                if i % 7:
                    continue
                for width, height, deck in sizes:
                    t = i * 0.08
                    fast = field_cells(field_geom(width, height, deck), height, mode, state, t)
                    ref = ref_field_cells(width, height, deck, mode, state, t)
                    self.assertEqual([sorted(r) for r in fast], [sorted(r) for r in ref], (mode, i, width))
                    checked += sum(len(r) for r in ref)
            self.assertGreater(checked, 100, mode)  # the comparison saw lit cells


class WaveFastPathTests(unittest.TestCase):
    def test_smooth_curve_and_heights_are_unchanged(self):
        rng = random.Random(5)
        for _ in range(200):
            bands = [rng.random() for _ in range(10)]
            cols = rng.choice([2, 10, 57, 189, 380])
            self.assertEqual(interpolate_smooth(bands, cols), ref_interpolate_smooth(bands, cols))
            phase, energy = rng.random() * 6.3, rng.choice([0.0, rng.random()])
            self.assertEqual(wave_heights(bands, cols, 7, phase, energy), ref_wave_heights(bands, cols, 7, phase, energy))

    def test_cached_trail_layer_draws_the_same_pixels(self):
        rng = random.Random(9)
        for palette in (FALLBACK, palette_named("mint")):
            lcd = LcdState()
            for i, bands in enumerate(music(rng, 60)):
                lcd.set_bands(bands)
                for f in range(5):
                    lcd.advance(1 / 60)
                    if (i * 5 + f) % 11:
                        continue
                    for scale in (1, 2):
                        cached = cairo.ImageSurface(cairo.FORMAT_ARGB32, 568 * scale, 84 * scale)
                        cr = cairo.Context(cached)
                        cr.scale(scale, scale)
                        paint_lcd(cr, 568, 84, "wave", palette, lcd)  # may hit the cache
                        lcd._trail_dots = None  # force the trail to be laid out again
                        fresh = cairo.ImageSurface(cairo.FORMAT_ARGB32, 568 * scale, 84 * scale)
                        cr = cairo.Context(fresh)
                        cr.scale(scale, scale)
                        paint_lcd(cr, 568, 84, "wave", palette, lcd)
                        self.assertEqual(bytes(cached.get_data()), bytes(fresh.get_data()), (i, f, scale))


class _Clock:
    def __init__(self):
        self.t = 0

    def get_frame_time(self):
        self.t += 16_667
        return self.t


class IdleWidgetTests(unittest.TestCase):
    def test_field_does_not_redraw_while_it_stays_dark(self):
        from music_player.widgets.field import FieldView

        view = FieldView()
        queued = []
        view.queue_draw = lambda: queued.append(1)
        view.set_bands([0.0] * 10)
        self.assertEqual(len(queued), 1)  # nothing drawn yet: draw once
        view._dark_drawn = True  # what do_snapshot records after a dark frame
        for _ in range(5):
            view.set_bands([0.0] * 10)
        self.assertEqual(len(queued), 1)
        view.set_bands([0.7] * 10)
        self.assertEqual(len(queued), 2)
        view.set_mode("waterfall")  # a new look always repaints
        self.assertFalse(view._dark_drawn)

    def test_strip_releases_the_frame_clock_when_settled(self):
        from music_player.widgets.spectrum import SpectrumView

        view = SpectrumView()
        clock = _Clock()
        self.assertTrue(view._tick_id)
        self.assertFalse(view._on_tick(view, clock))  # silent: the callback removes itself
        self.assertEqual(view._tick_id, 0)
        view.set_bands([0.6] * 10)
        self.assertTrue(view._awake)
        self.assertTrue(view._tick_id)  # sound brought it back
        self.assertTrue(view._on_tick(view, clock))


class VisOffTests(unittest.TestCase):
    def test_off_strip_is_the_bricks_resting_grid_whatever_played(self):
        lcd = LcdState()
        for bands in music(random.Random(1), 30):
            lcd.set_bands(bands)
            lcd.advance(0.08)
        off = cairo.ImageSurface(cairo.FORMAT_ARGB32, 568, 84)
        paint_lcd(cairo.Context(off), 568, 84, "off", FALLBACK, lcd, hover=4)
        rest = cairo.ImageSurface(cairo.FORMAT_ARGB32, 568, 84)
        paint_lcd(cairo.Context(rest), 568, 84, "bricks", FALLBACK, LcdState())
        self.assertEqual(bytes(off.get_data()), bytes(rest.get_data()))

    def test_off_field_has_no_lit_cells(self):
        state = FieldState()
        state.set_volume(70)
        for bands in music(random.Random(2), 60)[:20]:
            state.set_bands(bands)
        geom = field_geom(1916, 1570, (368.0, 385.0, 1548.0, 1185.0))
        self.assertTrue(any(field_cells(geom, 1570, "bricks", state, 1.0)))
        self.assertEqual(field_cells(geom, 1570, "off", state, 1.0), ([], [], []))

    def test_off_widgets_ignore_bands_and_stop_redrawing(self):
        from music_player.widgets.field import FieldView
        from music_player.widgets.spectrum import SpectrumView

        strip, field = SpectrumView(), FieldView()
        strip.set_volume(40)
        field.set_volume(40)
        strip.set_bands([0.8] * 10)
        field.set_bands([0.8] * 10)
        strip.set_mode("off")
        field.set_mode("off")
        queued = []
        strip.queue_draw = lambda: queued.append("strip")
        field.queue_draw = lambda: queued.append("field")
        clock = _Clock()
        self.assertFalse(strip._on_tick(strip, clock))  # the frame callback removes itself
        self.assertEqual(strip._tick_id, 0)
        for _ in range(5):
            strip.set_bands([0.9] * 10)
            field.set_bands([0.9] * 10)
        self.assertEqual(queued, [])
        self.assertEqual(strip._tick_id, 0)
        # back on: from rest, at the same volume, and animating again
        strip.set_mode("wave")
        field.set_mode("wave")
        self.assertEqual(strip.state.target, LcdState().target)
        self.assertEqual(strip.state.intensity, field.state.intensity)
        self.assertNotEqual(strip.state.intensity, LcdState().intensity)
        self.assertFalse(any(field.state.level))
        strip.set_bands([0.9] * 10)
        field.set_bands([0.9] * 10)
        self.assertTrue(strip._awake and strip._tick_id)
        self.assertIn("field", queued)
