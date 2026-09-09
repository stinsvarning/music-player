import unittest

from music_player.spectrum import (
    BRICK_COLS,
    BRICK_SEGS,
    VIS_MODES,
    bar_index_at,
    brick_columns,
    cycle_vis,
    field_band_at,
    field_clearance,
    field_level,
    field_spec,
    interpolate_bars,
    tick_brick_peaks,
    tick_peaks,
)
from music_player.prefs import load_vis_mode, save_vis_mode
from music_player.theme import FALLBACK
from music_player.widgets.field import FieldView
from music_player.widgets.spectrum import SpectrumView


class VisModeTests(unittest.TestCase):
    def test_three_named_modes_cycle(self):
        self.assertEqual(VIS_MODES, ("bricks", "wave", "orbit"))
        self.assertEqual(cycle_vis("bricks"), "wave")
        self.assertEqual(cycle_vis("wave"), "orbit")
        self.assertEqual(cycle_vis("orbit"), "bricks")
        self.assertEqual(cycle_vis("nope"), "bricks")

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
        save_vis_mode("orbit", path)
        self.assertEqual(load_vis_mode(path), "orbit")
        self.assertIn('cookies_from = "auto"', path.read_text())


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

    def test_orbit_field_has_angular_contrast(self):
        bands = [1.0] * 10
        kw = dict(mid_x=400.0, mid_y=400.0, half=400.0, height=800.0, cell=8.0, bands=bands, t=0.0)
        spoke = field_spec("orbit", cx=780.0, cy=400.0, **kw)
        gap = field_spec("orbit", cx=668.0, cy=668.0, **kw)
        self.assertGreater(spoke, gap)
        self.assertGreater(spoke, 0.2)


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
        view.set_bands([1, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(len(view._cols), BRICK_COLS)
        self.assertGreater(view._cols[0], 0)


if __name__ == "__main__":
    unittest.main()
