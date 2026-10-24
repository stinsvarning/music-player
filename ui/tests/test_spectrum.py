import unittest

from collections import deque

import cairo

from music_player.spectrum import (
    BRICK_COLS,
    BRICK_SEGS,
    VIS_MODES,
    WATERFALL_STEPS,
    Dynamics,
    FieldState,
    LcdState,
    band_at_height,
    bar_index_at,
    brick_columns,
    band_z,
    loudness,
    cycle_vis,
    ease_levels,
    fall_peaks,
    field_band_at,
    field_clearance,
    field_level,
    field_spec,
    gate,
    interpolate_bars,
    interpolate_smooth,
    normalize_vis,
    tick_brick_peaks,
    tick_peaks,
    waterfall_step,
    wave_row,
)
from music_player.widgets.vis_paint import paint_field, paint_lcd
from music_player.prefs import load_vis_mode, save_vis_mode
from music_player.theme import FALLBACK
from music_player.widgets.field import FieldView
from music_player.widgets.spectrum import SpectrumView


class VisModeTests(unittest.TestCase):
    def test_three_named_modes_cycle(self):
        self.assertEqual(VIS_MODES, ("bricks", "wave", "waterfall"))
        self.assertEqual(cycle_vis("bricks"), "wave")
        self.assertEqual(cycle_vis("wave"), "waterfall")
        self.assertEqual(cycle_vis("waterfall"), "bricks")
        self.assertEqual(cycle_vis("nope"), "bricks")

    def test_old_orbit_maps_to_waterfall(self):
        self.assertEqual(normalize_vis("orbit"), "waterfall")
        self.assertEqual(normalize_vis(" Waterfall "), "waterfall")
        self.assertEqual(normalize_vis("nope"), "bricks")
        self.assertEqual(normalize_vis(None), "bricks")
        self.assertEqual(cycle_vis("orbit"), "bricks")
        view = SpectrumView()
        view.set_mode("orbit")
        self.assertEqual(view.mode, "waterfall")
        field = FieldView()
        field.set_mode("bogus")
        self.assertEqual(field.mode, "bricks")

    def test_meter_and_field_share_a_mode(self):
        meter = SpectrumView()
        field = FieldView()
        self.assertEqual(meter.mode, "bricks")
        self.assertEqual(field.mode, "bricks")
        meter.set_mode("wave")
        field.set_mode("wave")
        self.assertEqual(meter.mode, "wave")
        self.assertEqual(field.mode, "wave")

    def test_vis_mode_round_trips_in_config_without_clobbering_cookies(self):
        from pathlib import Path
        import tempfile

        path = Path(tempfile.mkdtemp()) / "config.toml"
        path.write_text('cookies_from = "auto"\n')
        save_vis_mode("waterfall", path)
        self.assertEqual(load_vis_mode(path), "waterfall")
        self.assertIn('cookies_from = "auto"', path.read_text())

    def test_old_orbit_config_loads_as_waterfall(self):
        from pathlib import Path
        import tempfile

        path = Path(tempfile.mkdtemp()) / "config.toml"
        path.write_text('vis_mode = "orbit"\n')
        self.assertEqual(load_vis_mode(path), "waterfall")
        path.write_text('vis_mode = "spiral"\n')
        self.assertEqual(load_vis_mode(path), "bricks")
        save_vis_mode("orbit", path)
        self.assertIn('vis_mode = "waterfall"', path.read_text())


class InterpolateTests(unittest.TestCase):
    def test_expands_ten_to_display_cols(self):
        bars = interpolate_bars([0, 0.2, 0.4, 0.6, 0.8, 1, 0.8, 0.4, 0.2, 0], count=BRICK_COLS)
        self.assertEqual(len(bars), BRICK_COLS)
        self.assertGreater(max(bars), 0.9)
        self.assertGreaterEqual(min(bars), 0.0)
        self.assertLessEqual(max(bars), 1.0)

    def test_empty_is_silence(self):
        self.assertEqual(interpolate_bars([], count=BRICK_COLS), [0.0] * BRICK_COLS)

    def test_many_frames_keep_bar_and_peak_lengths(self):
        bands = [0.0] * 10
        peaks: list[float] = []
        bricks: list[int] = []
        for frame in range(60):
            bands[frame % 10] = (frame % 8) / 8
            bars = interpolate_bars(bands, BRICK_COLS)
            peaks = tick_peaks(peaks, bars)
            cols = brick_columns(bands)
            bricks = tick_brick_peaks(bricks, cols)
            self.assertEqual(len(bars), BRICK_COLS)
            self.assertEqual(len(peaks), BRICK_COLS)
            self.assertEqual(len(cols), BRICK_COLS)
            self.assertEqual(len(bricks), BRICK_COLS)
            self.assertTrue(all(0 <= c <= BRICK_SEGS for c in cols))


class PeakTests(unittest.TestCase):
    def test_peaks_hold_then_fall(self):
        peaks = tick_peaks([0.0] * 4, [0.8, 0.1, 0.0, 0.5], decay=0.08)
        self.assertGreaterEqual(peaks[0], 0.8)
        fallen = tick_peaks(peaks, [0.0, 0.0, 0.0, 0.0], decay=0.08)
        self.assertLess(fallen[0], peaks[0])
        self.assertGreater(fallen[0], 0.0)

    def test_brick_peaks_drop_one_seg(self):
        peaks = tick_brick_peaks([0, 0, 0], [8, 1, 0])
        self.assertEqual(peaks[0], 8)
        fallen = tick_brick_peaks(peaks, [0, 0, 0])
        self.assertEqual(fallen[0], 7)


class FieldTests(unittest.TestCase):
    def test_bass_lights_the_edges(self):
        bands = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        edge = field_band_at(20, 500, 500, bands)
        center = field_band_at(500, 500, 500, bands)
        self.assertGreater(edge, center)
        self.assertGreater(field_level(1.0, bands), field_level(0.0, bands))

    def test_clearance_is_zero_inside_the_deck(self):
        self.assertEqual(field_clearance(0, 0), 0.0)
        self.assertGreater(field_clearance(300, 0), field_clearance(80, 0))
        self.assertLessEqual(field_clearance(800, 800), 1.0)

    def test_wave_field_is_radial_and_dense_at_the_edge(self):
        bands = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        kw = dict(mid_x=400.0, mid_y=300.0, half=400.0, height=600.0, cell=8.0, bands=bands, t=0.4)
        edge = field_spec("wave", cx=40.0, cy=300.0, **kw)
        core = field_spec("wave", cx=400.0, cy=300.0, **kw)
        self.assertGreater(edge, core)

    def test_wave_field_swells_from_the_bass_edges(self):
        loud = [0.9, 0.9, 0.9] + [0.0] * 7
        kw = dict(mid_x=1000.0, mid_y=500.0, half=1000.0, height=1000.0, cell=20.0, t=0.0)
        edge = field_spec("wave", cx=1980.0, cy=560.0, bands=loud, **kw)
        near = field_spec("wave", cx=1250.0, cy=560.0, bands=loud, **kw)
        far_off_line = field_spec("wave", cx=1980.0, cy=980.0, bands=loud, **kw)
        silent = field_spec("wave", cx=1980.0, cy=560.0, bands=[0.0] * 10, **kw)
        self.assertGreater(edge, near)
        self.assertGreater(edge, far_off_line)
        self.assertGreater(edge, silent)
        self.assertLess(silent, 0.15)

    def test_waterfall_field_drifts_outward(self):
        history = deque([[0.0] * 10 for _ in range(30)])
        history.append([1.0] * 10)  # newest frame is loud
        kw = dict(cx=0.0, cy=500.0, mid_x=1000.0, mid_y=500.0, half=1000.0, height=1000.0, cell=20.0, bands=[0.0] * 10, t=0.0)
        fresh = field_spec("waterfall", ring=5.0, history=history, **kw)
        old = field_spec("waterfall", ring=200.0, history=history, **kw)
        self.assertGreater(fresh, 0.3)
        self.assertEqual(old, 0.0)
        for _ in range(10):
            history.append([0.0] * 10)
        self.assertGreater(field_spec("waterfall", ring=200.0, history=history, **kw), 0.3)
        self.assertEqual(field_spec("waterfall", ring=5.0, history=deque(), **kw), 0.0)

    def test_waterfall_rows_put_bass_at_the_bottom(self):
        bands = [1.0] + [0.0] * 9
        self.assertGreater(band_at_height(990, 1000, bands), band_at_height(10, 1000, bands))

    def test_bricks_field_is_dark_when_quiet(self):
        kw = dict(cx=20.0, cy=990.0, mid_x=500.0, mid_y=500.0, half=500.0, height=1000.0, cell=10.0, t=0.0)
        self.assertEqual(field_spec("bricks", bands=[0.05] * 10, **kw), 0.0)
        self.assertGreater(field_spec("bricks", bands=[0.9] * 10, **kw), 0.5)


class SmoothingTests(unittest.TestCase):
    def test_fast_attack_slow_release(self):
        up = ease_levels([0.0], [1.0], 0.016, attack=0.025, release=0.2)[0]
        down = 1.0 - ease_levels([1.0], [0.0], 0.016, attack=0.025, release=0.2)[0]
        self.assertGreater(up, down * 3)
        self.assertEqual(ease_levels([0.2, 0.3], [0.5, 0.5], 0.0, 0.1, 0.1), [0.2, 0.3])
        self.assertEqual(len(ease_levels([], [0.1] * 4, 0.1, 0.1, 0.1)), 4)

    def test_frame_rate_independent(self):
        a = [0.0]
        for _ in range(4):
            a = ease_levels(a, [1.0], 0.01, 0.05, 0.2)
        b = ease_levels([0.0], [1.0], 0.04, 0.05, 0.2)
        self.assertAlmostEqual(a[0], b[0], places=6)

    def test_gate_silences_the_floor(self):
        self.assertEqual(gate(0.03), 0.0)
        self.assertGreater(gate(0.5), 0.3)
        self.assertEqual(gate(1.0), 1.0)

    def test_peak_caps_hold_then_fall_with_gravity(self):
        peaks, holds, vels = fall_peaks([0.0], [0.0], [0.0], [0.8], 0.016)
        self.assertAlmostEqual(peaks[0], 0.8)
        for _ in range(10):  # 0.16 s, still holding
            peaks, holds, vels = fall_peaks(peaks, holds, vels, [0.0], 0.016)
        self.assertAlmostEqual(peaks[0], 0.8)
        drops = []
        for _ in range(40):
            before = peaks[0]
            peaks, holds, vels = fall_peaks(peaks, holds, vels, [0.0], 0.016)
            drops.append(before - peaks[0])
        self.assertLess(peaks[0], 0.8)
        self.assertGreater(drops[-1], drops[len(drops) // 2 - 5])  # accelerates
        for _ in range(200):
            peaks, holds, vels = fall_peaks(peaks, holds, vels, [0.0], 0.016)
        self.assertEqual(peaks[0], 0.0)

    def test_dynamics_shows_hits_against_a_flat_loud_bed(self):
        import random

        rng = random.Random(3)
        dyn = Dynamics()
        for _ in range(200):  # real loud music: ~0.7 with +-0.03 jitter
            level, events = dyn.apply([0.7 + 0.03 * (rng.random() - 0.5) for _ in range(10)])
        self.assertTrue(all(0.1 < v < 0.7 for v in level), level)
        self.assertLess(max(events), 0.3)
        level, events = dyn.apply([0.82] + [0.7] * 9)  # a kick
        self.assertGreater(level[0], 0.75)
        self.assertGreater(events[0], 0.5)
        self.assertLess(max(events[1:]), 0.2)

    def test_dynamics_keeps_quiet_music_quiet_and_silence_dark(self):
        import random

        rng = random.Random(4)
        loud, quiet = Dynamics(), Dynamics()
        for _ in range(200):
            jitter = [0.04 * (rng.random() - 0.5) for _ in range(10)]
            hi, _ = loud.apply([0.7 + j for j in jitter])
            lo, _ = quiet.apply([0.32 + j for j in jitter])
        self.assertLess(max(lo), max(hi) * 0.5)
        for _ in range(20):
            level, events = loud.apply([0.0] * 10)
        self.assertEqual(max(level), 0.0)
        self.assertEqual(max(events), 0.0)
        self.assertEqual(loudness([0.1] * 10), 0.0)
        self.assertEqual(loudness([0.9] * 10), 1.0)
        self.assertGreater(band_z(0.8, 0.7, 0.03), 2.0)
        self.assertLessEqual(band_z(5.0, 0.0, 0.0), 3.5)

    def test_smooth_interpolation_passes_through_bands(self):
        bands = [0.0, 1.0, 0.0, 0.5, 0.2, 0.2, 0.9, 0.1, 0.0, 0.3]
        out = interpolate_smooth(bands, 10)
        for a, b in zip(out, bands):
            self.assertAlmostEqual(a, b)
        many = interpolate_smooth(bands, 200)
        self.assertEqual(len(many), 200)
        self.assertTrue(all(0.0 <= v <= 1.0 for v in many))
        self.assertEqual(interpolate_smooth([], 5), [0.0] * 5)

    def test_wave_rows_and_waterfall_steps(self):
        self.assertEqual(wave_row(0.0, 10), 0)
        self.assertEqual(wave_row(1.0, 10), 9)
        self.assertLess(wave_row(0.3, 10), wave_row(0.7, 10))
        self.assertEqual(waterfall_step(0.05), 0)
        self.assertEqual(waterfall_step(1.0), WATERFALL_STEPS)
        self.assertLess(waterfall_step(0.4), waterfall_step(0.8))


class StateTests(unittest.TestCase):
    def test_lcd_state_settles_to_rest(self):
        state = LcdState()
        for _ in range(20):
            state.set_bands([0.3, 0.9, 0.5, 0.2, 0.7, 0.4, 0.6, 0.1, 0.8, 0.3])
            state.advance(0.08)
        self.assertGreater(max(state.peaks), 0.2)
        self.assertEqual(len(state.trail), 2)
        state.set_bands([0.0] * 10)
        for _ in range(400):
            active = state.advance(1 / 60)
        self.assertFalse(active)
        self.assertEqual(max(state.peaks), 0.0)

    def test_waterfall_history_grows_one_column_per_update(self):
        state = LcdState()
        for i in range(5):
            state.set_bands([0.5] * 10)
        self.assertEqual(len(state.history), 5)

    def test_field_state_drifts_every_other_update(self):
        state = FieldState()
        for _ in range(10):
            state.set_bands([0.6] * 10)
        self.assertEqual(len(state.history), 6)  # the first update seeds it, then every 2nd
        self.assertIs(state.bands_for("wave"), state.slow)
        self.assertIs(state.bands_for("bricks"), state.level)


class PaintTests(unittest.TestCase):
    def test_every_mode_paints_offscreen(self):
        lcd = LcdState()
        field = FieldState()
        for i in range(30):
            bands = [((i + b) % 7) / 7 for b in range(10)]
            lcd.set_bands(bands)
            field.set_bands(bands)
            lcd.advance(0.08)
        for mode in VIS_MODES:
            surf = cairo.ImageSurface(cairo.FORMAT_RGB24, 568, 84)
            paint_lcd(cairo.Context(surf), 568, 84, mode, FALLBACK, lcd, hover=3)
            big = cairo.ImageSurface(cairo.FORMAT_RGB24, 640, 360)
            paint_field(cairo.Context(big), 640, 360, (200, 100, 440, 260), mode, FALLBACK, field, 1.0)
            data = bytes(surf.get_data())
            self.assertGreater(len(set(data[i : i + 4] for i in range(0, len(data), 4))), 2, mode)


class HitTests(unittest.TestCase):
    def test_pointer_x_maps_to_bar_index(self):
        self.assertEqual(bar_index_at(0, 360, 36), 0)
        self.assertLess(bar_index_at(20, 360, 36), bar_index_at(340, 360, 36))
        self.assertEqual(bar_index_at(400, 360, 36), 35)
        self.assertEqual(bar_index_at(-8, 360, 36), 0)
        self.assertEqual(bar_index_at(10, 0, 36), 0)

    def test_meter_uses_palette(self):
        view = SpectrumView()
        view.set_palette(FALLBACK)
        self.assertEqual(view.palette.accent, FALLBACK.accent)
        self.assertEqual(view.palette.peak, FALLBACK.peak)
        view.set_bands([1.0] + [0.7] * 9)
        self.assertEqual(len(view._cols), BRICK_COLS)
        self.assertEqual(len(view.state.history), 1)
        self.assertGreater(view._cols[0], 0)


if __name__ == "__main__":
    unittest.main()
