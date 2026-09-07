import unittest

from music_player.spectrum import LOOKS, bar_index_at, cycle_look, interpolate_bars, tick_peaks
from music_player.theme import FALLBACK
from music_player.widgets.spectrum import SpectrumView


class InterpolateTests(unittest.TestCase):
    def test_expands_ten_to_thirty_six(self):
        bars = interpolate_bars([0, 0.2, 0.4, 0.6, 0.8, 1, 0.8, 0.4, 0.2, 0], count=36)
        self.assertEqual(len(bars), 36)
        self.assertGreater(max(bars), 0.9)
        self.assertGreaterEqual(min(bars), 0.0)
        self.assertLessEqual(max(bars), 1.0)

    def test_empty_is_silence(self):
        self.assertEqual(interpolate_bars([], count=36), [0.0] * 36)

    def test_many_frames_keep_bar_and_peak_lengths(self):
        bands = [0.0] * 10
        peaks: list[float] = []
        for frame in range(60):
            bands[frame % 10] = (frame % 8) / 8
            bars = interpolate_bars(bands, 36)
            peaks = tick_peaks(peaks, bars)
            self.assertEqual(len(bars), 36)
            self.assertEqual(len(peaks), 36)


class PeakTests(unittest.TestCase):
    def test_peaks_hold_then_fall(self):
        peaks = tick_peaks([0.0] * 4, [0.8, 0.1, 0.0, 0.5], decay=0.08)
        self.assertGreaterEqual(peaks[0], 0.8)
        fallen = tick_peaks(peaks, [0.0, 0.0, 0.0, 0.0], decay=0.08)
        self.assertLess(fallen[0], peaks[0])
        self.assertGreater(fallen[0], 0.0)


class LookAndHitTests(unittest.TestCase):
    def test_two_looks_cycle(self):
        self.assertGreaterEqual(len(LOOKS), 2)
        first = LOOKS[0]
        second = cycle_look(first)
        self.assertIn(second, LOOKS)
        self.assertNotEqual(second, first)
        seen = {first, second}
        current = second
        for _ in range(len(LOOKS) + 2):
            current = cycle_look(current)
            seen.add(current)
        self.assertEqual(seen, set(LOOKS))
        self.assertEqual(cycle_look("nope"), LOOKS[0])

    def test_pointer_x_maps_to_bar_index(self):
        self.assertEqual(bar_index_at(0, 360, 36), 0)
        self.assertLess(bar_index_at(20, 360, 36), bar_index_at(340, 360, 36))
        self.assertEqual(bar_index_at(400, 360, 36), 35)
        self.assertEqual(bar_index_at(-8, 360, 36), 0)
        self.assertEqual(bar_index_at(10, 0, 36), 0)

    def test_view_press_cycles_look_and_uses_palette(self):
        view = SpectrumView()
        view.set_palette(FALLBACK)
        self.assertEqual(view.palette.accent, FALLBACK.accent)
        self.assertEqual(view.palette.peak, FALLBACK.peak)
        self.assertIn(view.look, LOOKS)
        first = view.look
        view.cycle_look()
        self.assertNotEqual(view.look, first)
        self.assertIn(view.look, LOOKS)
        view.cycle_look()
        if len(LOOKS) == 2:
            self.assertEqual(view.look, first)


if __name__ == "__main__":
    unittest.main()
