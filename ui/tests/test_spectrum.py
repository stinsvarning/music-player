import unittest

from music_player.spectrum import (
    BRICK_COLS,
    BRICK_SEGS,
    bar_index_at,
    brick_columns,
    interpolate_bars,
    tick_brick_peaks,
    tick_peaks,
)
from music_player.theme import FALLBACK
from music_player.widgets.spectrum import SpectrumView


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
