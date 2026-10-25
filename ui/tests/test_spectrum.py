import unittest

from collections import deque

import cairo

from music_player.spectrum import (
    BRICK_COLS,
    BRICK_SEGS,
    VIS_MODES,
    WATERFALL_STEPS,
    Dynamics,
    FramePacer,
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
    wave_heights,
    wave_row,
    volume_intensity,
)
from music_player.widgets.vis_paint import paint_field, paint_lcd
from music_player.prefs import config_vis_mode, initial_vis_mode, load_vis_mode, saved_vis_mode
from music_player.theme import FALLBACK
from music_player.widgets.field import FieldView
from music_player.widgets.spectrum import SpectrumView


class VisModeTests(unittest.TestCase):
    def test_three_looks_then_off_cycle(self):
        self.assertEqual(VIS_MODES, ("bricks", "wave", "waterfall"))
        self.assertEqual(cycle_vis("bricks"), "wave")
        self.assertEqual(cycle_vis("wave"), "waterfall")
        self.assertEqual(cycle_vis("waterfall"), "off")
        self.assertEqual(cycle_vis("off"), "bricks")
        self.assertEqual(cycle_vis("nope"), "bricks")
        self.assertEqual(normalize_vis(" OFF "), "off")

    def test_old_orbit_maps_to_waterfall(self):
        self.assertEqual(normalize_vis("orbit"), "waterfall")
        self.assertEqual(normalize_vis(" Waterfall "), "waterfall")
        self.assertEqual(normalize_vis("nope"), "bricks")
        self.assertEqual(normalize_vis(None), "bricks")
        self.assertEqual(cycle_vis("orbit"), "off")
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

    def test_config_vis_mode_accepts_off_and_the_orbit_alias(self):
        from pathlib import Path
        import tempfile

        path = Path(tempfile.mkdtemp()) / "config.toml"
        path.write_text('cookies_from = "auto"\n')
        self.assertIsNone(config_vis_mode(path))
        self.assertEqual(load_vis_mode(path), "bricks")
        path.write_text('vis_mode = "off"  # quiet\n')
        self.assertEqual(config_vis_mode(path), "off")
        path.write_text('vis_mode = "orbit"\n')
        self.assertEqual(load_vis_mode(path), "waterfall")
        path.write_text('vis_mode = "spiral"\n')
        self.assertEqual(load_vis_mode(path), "bricks")

    def test_saved_choice_beats_config_which_beats_bricks(self):
        import json
        import os
        from pathlib import Path
        import tempfile

        folder = Path(tempfile.mkdtemp())
        cfg, session = folder / "config.toml", folder / "session.json"
        old = {k: os.environ.get(k) for k in ("MUSIC_PLAYER_CONFIG", "MUSIC_PLAYER_SESSION")}
        os.environ["MUSIC_PLAYER_CONFIG"] = str(cfg)
        os.environ.pop("MUSIC_PLAYER_SESSION", None)
        try:
            self.assertEqual(initial_vis_mode(), "bricks")
            cfg.write_text('vis_mode = "wave"\n')
            self.assertEqual(initial_vis_mode(), "wave")
            session.write_text(json.dumps({"version": 1, "vis_mode": None, "tracks": []}))
            self.assertEqual(initial_vis_mode(), "wave")  # nothing saved yet
            session.write_text(json.dumps({"version": 1, "vis_mode": "off", "tracks": []}))
            self.assertEqual(saved_vis_mode(), "off")
            self.assertEqual(initial_vis_mode(), "off")
            session.write_text("{broken")
            self.assertEqual(initial_vis_mode(), "wave")
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


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
        self.assertIs(state.bands_for("wave"), state.wave)
        self.assertIs(state.bands_for("bricks"), state.bricks)
        self.assertIs(state.bands_for("waterfall"), state.level)


class LivelierTests(unittest.TestCase):
    def test_bricks_use_more_range_and_hits_pop(self):
        state = LcdState()
        for _ in range(60):
            state.set_bands([0.7] * 10)
            state.advance(0.08)
        calm = max(state.punch)
        state.set_bands([0.85] + [0.7] * 9)
        self.assertGreater(state.punch[0], calm + 0.3)
        state.advance(1 / 60)
        self.assertGreater(state.level[0], calm + 0.2)  # fast attack: most of it in one frame
        self.assertGreater(state.peak_holds[0], 0.0)

    def test_wave_heights_move_and_rest_flat(self):
        flat = wave_heights([0.0] * 10, 100, 7, phase=1.0, energy=0.0)
        self.assertEqual(max(flat), 0.0)
        a = wave_heights([0.5] * 10, 100, 7, phase=0.0, energy=0.4)
        b = wave_heights([0.5] * 10, 100, 7, phase=1.0, energy=0.4)
        self.assertGreater(max(abs(x - y) for x, y in zip(a, b)), 0.5)  # the ripple travels
        self.assertTrue(all(0.0 <= h <= 6.0 for h in a + b))
        self.assertNotEqual(a[0], a[50])
        self.assertEqual(wave_heights([0.5] * 10, 0, 7), [])


class PaintTests(unittest.TestCase):
    def test_field_is_dark_at_rest(self):
        field = FieldState()
        for _ in range(10):
            field.set_bands([0.0] * 10)
        for mode in VIS_MODES:
            surf = cairo.ImageSurface(cairo.FORMAT_RGB24, 640, 360)
            paint_field(cairo.Context(surf), 640, 360, (200, 100, 440, 260), mode, FALLBACK, field, 3.0)
            data = bytes(surf.get_data())
            bright = max(max(data[i], data[i + 1], data[i + 2]) for i in range(0, len(data), 4))
            self.assertLess(bright, 40, mode)  # bg (#121212) plus the faint grid only

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


class VolumeTests(unittest.TestCase):
    def test_volume_curve_has_a_floor_and_is_full_at_100(self):
        self.assertAlmostEqual(volume_intensity(100), 1.0)
        self.assertAlmostEqual(volume_intensity(0), 0.25)
        self.assertAlmostEqual(volume_intensity(50), 0.25 + 0.75 * 0.5**0.7)
        self.assertAlmostEqual(volume_intensity(None), 1.0)
        self.assertAlmostEqual(volume_intensity(250), 1.0)
        self.assertAlmostEqual(volume_intensity(-5), 0.25)
        steps = [volume_intensity(v) for v in range(0, 101, 10)]
        self.assertEqual(steps, sorted(steps))
        self.assertGreater(volume_intensity(20), 0.25 + 0.75 * 0.2)  # perceptual: low volumes stay visible

    def _strip(self, volume):
        state = LcdState()
        state.set_volume(volume)
        for i in range(60):
            state.set_bands([0.7 + 0.1 * ((i + b) % 3 == 0) for b in range(10)])
            state.advance(0.08)
        return state

    def test_strip_calms_with_volume(self):
        full, low = self._strip(100), self._strip(10)
        self.assertGreater(sum(full.punch), sum(low.punch) * 1.5)
        self.assertGreater(sum(full.wave_target), sum(low.wave_target) * 1.5)
        self.assertGreater(full.energy, low.energy * 1.5)
        self.assertGreater(max(low.bars), 0.0)  # still visible at low volume

    def test_field_calms_with_volume(self):
        fields = {}
        for vol in (100, 10):
            f = FieldState()
            f.set_volume(vol)
            for i in range(60):
                f.set_bands([0.7 + 0.1 * ((i + b) % 3 == 0) for b in range(10)])
            fields[vol] = f
        for attr in ("level", "bricks", "wave"):
            self.assertGreater(sum(getattr(fields[100], attr)), sum(getattr(fields[10], attr)) * 1.5, attr)
        self.assertGreater(sum(fields[10].bricks), 0.0)

    def test_full_volume_matches_no_volume(self):
        a, b = LcdState(), LcdState()
        a.set_volume(100)
        for i in range(20):
            bands = [((i + k) % 7) / 7 for k in range(10)]
            a.set_bands(bands)
            b.set_bands(bands)
        self.assertEqual(a.punch, b.punch)
        self.assertEqual(list(a.history), list(b.history))


class PacerTests(unittest.TestCase):
    def _draws(self, hz, seconds=2.0):
        pacer = FramePacer(60)
        pacer.reset()
        n, total = 0, 0.0
        for _ in range(int(hz * seconds)):
            step = pacer.step(1 / hz)
            if step is not None:
                n += 1
                total += step
        return n / seconds, total

    def test_caps_at_60_on_fast_monitors(self):
        for hz in (120, 144, 165, 240):
            fps, total = self._draws(hz)
            self.assertLessEqual(fps, 61, hz)
            self.assertGreaterEqual(fps, 55, hz)
            self.assertAlmostEqual(total, 2.0, delta=0.05)  # time is never lost

    def test_60hz_and_slower_draw_every_frame(self):
        self.assertAlmostEqual(self._draws(60)[0], 60, delta=1)
        self.assertAlmostEqual(self._draws(30)[0], 30, delta=1)


class FieldPunchTests(unittest.TestCase):
    def test_bricks_field_climbs_on_hits(self):
        f = FieldState()
        for _ in range(60):
            f.set_bands([0.6] * 10)
        calm = f.bricks[0]
        for _ in range(3):
            f.set_bands([0.85] + [0.6] * 9)
        self.assertGreater(f.bricks[0], calm + 0.25)
        kw = dict(cx=20.0, mid_x=1000.0, mid_y=500.0, half=1000.0, height=1000.0, cell=20.0, t=0.0)
        high = field_spec("bricks", cy=1000.0 - 20 * 12, bands=[0.9] * 10, **kw)
        self.assertGreater(high, 0.2)  # a loud column reaches well above the floor

    def test_wave_field_reacts_within_a_few_polls(self):
        f = FieldState()
        for _ in range(60):
            f.set_bands([0.6] * 10)
        calm = f.wave[0]
        for _ in range(3):
            f.set_bands([0.85, 0.85, 0.85] + [0.6] * 7)
        self.assertGreater(f.wave[0], calm + 0.15)


class HaloTests(unittest.TestCase):
    def test_field_bg_is_uniform_around_the_deck(self):
        field = FieldState()
        for _ in range(10):
            field.set_bands([0.0] * 10)
        w, h, cell = 810, 400, 810 / 81
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h)
        paint_field(cairo.Context(surf), w, h, (300, 120, 510, 280), "bricks", FALLBACK, field, 0.0)
        data, stride = bytes(surf.get_data()), surf.get_stride()

        def px(x, y):
            o = int(y) * stride + int(x) * 4
            return data[o : o + 3]

        # cell centres just outside the deck vs far out in the corner: identical
        near = {px(c * cell + cell / 2, 125) for c in range(31, 34)} | {px(29 * cell + cell / 2, r * cell + cell / 2) for r in (14, 20, 26)}
        far = {px(c * cell + cell / 2, r * cell + cell / 2) for c in (1, 2) for r in (1, 2)}
        self.assertEqual(len(near | far), 1, (near, far))
