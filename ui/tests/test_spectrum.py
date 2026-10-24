import math
import unittest

from music_player.spectrum import (
    BRICK_COLS,
    BRICK_SEGS,
    ORBIT_FIELD_RINGS,
    ORBIT_LANES,
    ORBIT_RAIL,
    ORBIT_RING_INNER,
    ORBIT_RING_SPAN,
    VIS_MODES,
    bar_index_at,
    brick_columns,
    brick_heights,
    cycle_vis,
    decay_peaks,
    field_band_at,
    field_clearance,
    field_level,
    field_spec,
    fill_orbit_brightness,
    interpolate_bars,
    orbit_head_index,
    orbit_levels,
    orbit_path,
    orbit_ring_r,
    smooth_levels,
    tick_brick_peaks,
    tick_peaks,
    wave_reach,
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


class SmoothTests(unittest.TestCase):
    def test_attack_is_quicker_than_release(self):
        risen = smooth_levels([0.0], [1.0], 0.05)
        fallen = smooth_levels([1.0], [0.0], 0.05)
        self.assertGreater(risen[0], 1.0 - fallen[0])
        self.assertGreater(risen[0], 0.35)
        self.assertLess(fallen[0], 0.92)

    def test_stays_inside_the_unit_interval(self):
        out = smooth_levels([0.2, 2.0], [1.4, -0.5, 0.3], 0.05)
        self.assertEqual(len(out), 3)
        self.assertTrue(all(0.0 <= v <= 1.0 for v in out))

    def test_silence_releases_toward_zero(self):
        level = [1.0]
        for _ in range(40):
            level = smooth_levels(level, [0.0], 0.05)
        self.assertLess(level[0], 0.05)


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

    def test_time_based_peaks_hold_then_fall(self):
        held = decay_peaks([0.2], [0.9], 0.1, fall=1.0)
        self.assertAlmostEqual(held[0], 0.9)
        fallen = decay_peaks([0.9], [0.1], 0.08, fall=1.0)
        self.assertAlmostEqual(fallen[0], 0.82)
        stalled = decay_peaks([0.9], [0.1], 2.0, fall=1.0)
        self.assertAlmostEqual(stalled[0], 0.8)
        self.assertAlmostEqual(decay_peaks([0.2], [0.0], 0.0, fall=5.0)[0], 0.2)


class BrickShapeTests(unittest.TestCase):
    def test_fractional_heights_follow_the_band(self):
        heights = brick_heights([1, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(len(heights), BRICK_COLS)
        self.assertAlmostEqual(heights[0], float(BRICK_SEGS))
        self.assertGreater(heights[0], heights[-1])
        self.assertEqual(brick_columns([1, 0, 0, 0, 0, 0, 0, 0, 0, 0])[0], BRICK_SEGS)


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

    def test_bricks_field_rises_from_the_floor_with_a_separated_cap(self):
        bands = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        kw = dict(mid_x=400.0, mid_y=300.0, half=400.0, height=600.0, cell=8.0, bands=bands, t=0.0)
        edge = [field_spec("bricks", cx=10.0, cy=float(y), **kw) for y in range(0, 600, 2)]
        center = [field_spec("bricks", cx=400.0, cy=float(y), **kw) for y in range(0, 600, 2)]
        self.assertGreater(sum(v > 0.5 for v in edge), sum(v > 0.5 for v in center) + 8)
        self.assertEqual(edge[0], 0.0)
        self.assertGreater(edge[-1], 0.5)
        seen_cap = seen_gap = seen_body = False
        for value in edge:
            if not seen_cap and value >= 0.95:
                seen_cap = True
            elif seen_cap and not seen_gap and value == 0.0:
                seen_gap = True
            elif seen_gap and value >= 0.8:
                seen_body = True
                break
        self.assertTrue(seen_cap and seen_gap and seen_body)

    def test_wave_field_travels_outward_and_keeps_bass_at_the_edge(self):
        bass = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        kw = dict(mid_y=300.0, mid_x=400.0, half=400.0, height=600.0, cell=8.0, bands=bass)
        edge = [field_spec("wave", cx=float(x), cy=300.0, t=0.3, **kw) for x in range(16, 140, 4)]
        core = [field_spec("wave", cx=float(x), cy=300.0, t=0.3, **kw) for x in range(360, 440, 4)]
        self.assertGreater(max(edge), 0.7)
        self.assertGreater(max(edge), max(core) + 0.4)
        full = [1.0] * 10
        line = [
            field_spec(
                "wave",
                cx=float(x),
                cy=300.0,
                t=0.3,
                mid_x=400.0,
                mid_y=300.0,
                half=400.0,
                height=600.0,
                cell=8.0,
                bands=full,
            )
            for x in range(40, 760, 4)
        ]
        self.assertGreater(max(line), 0.8)
        self.assertLess(min(line), 0.05)
        drift = max(
            abs(
                field_spec("wave", cx=float(x), cy=300.0, t=0.0, **kw)
                - field_spec("wave", cx=float(x), cy=300.0, t=0.7, **kw)
            )
            for x in range(24, 200, 6)
        )
        self.assertGreater(drift, 0.4)

    def test_orbit_field_is_concentric_and_softly_rotating(self):
        bass = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        kw = dict(mid_x=400.0, mid_y=400.0, half=400.0, height=800.0, cell=8.0, bands=bass, t=0.4)
        reach = max(400.0, 800.0 * 0.5)

        def at(index: int, ang: float = 0.0) -> float:
            dist = orbit_ring_r(index) * reach
            return field_spec(
                "orbit",
                cx=400.0 + dist * math.cos(ang),
                cy=400.0 + dist * math.sin(ang),
                **kw,
            )

        outer = at(ORBIT_FIELD_RINGS - 1)
        inner = at(0)
        self.assertGreater(outer, 0.8)
        self.assertLess(inner, 0.05)
        step = ORBIT_RING_SPAN / ORBIT_FIELD_RINGS
        gap_r = (ORBIT_RING_INNER + (ORBIT_FIELD_RINGS - 1) * step) * reach
        gap = field_spec("orbit", cx=400.0 + gap_r, cy=400.0, **kw)
        self.assertLess(gap, 0.05)
        around = [at(ORBIT_FIELD_RINGS - 1, i * math.tau / 16) for i in range(16)]
        self.assertGreater(max(around), min(around))
        self.assertGreater(min(around), max(around) * 0.7)

    def test_field_spec_stays_inside_zero_and_one(self):
        bands = [0.2, 0.9, 0.4, 0.7, 0.1, 0.5, 0.8, 0.3, 0.6, 0.0]
        for mode in VIS_MODES:
            for cx in (0.0, 100.0, 400.0, 800.0):
                for cy in (0.0, 50.0, 300.0, 590.0):
                    value = field_spec(
                        mode,
                        cx=cx,
                        cy=cy,
                        mid_x=400.0,
                        mid_y=300.0,
                        half=400.0,
                        height=600.0,
                        cell=8.0,
                        bands=bands,
                        t=1.2,
                    )
                    self.assertGreaterEqual(value, 0.0)
                    self.assertLessEqual(value, 1.0)


class WaveShapeTests(unittest.TestCase):
    def test_waveform_is_not_a_flat_bar(self):
        vals = [wave_reach(i, BRICK_COLS, 1.0, 0.4) for i in range(BRICK_COLS)]
        self.assertGreater(max(vals) - min(vals), 0.35)
        self.assertGreater(max(vals), 0.85)
        self.assertLess(min(vals), 0.45)
        self.assertTrue(all(0.0 <= v <= 1.0 for v in vals))

    def test_silence_collapses_to_the_center_line(self):
        vals = [wave_reach(i, BRICK_COLS, 0.0, 1.2) for i in range(BRICK_COLS)]
        self.assertLess(max(vals), 0.16)

    def test_phase_moves_the_crest(self):
        drift = max(
            abs(wave_reach(i, BRICK_COLS, 1.0, 0.0) - wave_reach(i, BRICK_COLS, 1.0, 0.45))
            for i in range(BRICK_COLS)
        )
        self.assertGreater(drift, 0.2)


class OrbitShapeTests(unittest.TestCase):
    def test_outer_lane_is_bass_and_spans_the_strip(self):
        levels = orbit_levels([1.0, 0, 0, 0, 0, 0, 0, 0, 0, 0], ORBIT_LANES)
        self.assertEqual(len(levels), ORBIT_LANES)
        self.assertGreater(levels[0], 0.9)
        self.assertLess(levels[-1], 0.05)
        outer = orbit_path(BRICK_COLS, BRICK_SEGS, 0)
        cols = {c for c, _r in outer}
        rows = {r for _c, r in outer}
        self.assertIn(0, cols)
        self.assertIn(BRICK_COLS - 1, cols)
        self.assertIn(0, rows)
        self.assertIn(BRICK_SEGS - 1, rows)
        self.assertEqual(len(outer), len(set(outer)))

    def test_inner_lane_is_inset_and_mirrored(self):
        inner = orbit_path(BRICK_COLS, BRICK_SEGS, ORBIT_LANES - 1)
        cols = {c for c, _r in inner}
        self.assertGreater(min(cols), 2)
        self.assertLess(max(cols), BRICK_COLS - 3)
        for lane in range(ORBIT_LANES):
            path = set(orbit_path(BRICK_COLS, BRICK_SEGS, lane))
            for c, r in path:
                self.assertIn((c, BRICK_SEGS - 1 - r), path)

    def test_paths_are_cached(self):
        self.assertIs(orbit_path(BRICK_COLS, BRICK_SEGS, 0), orbit_path(BRICK_COLS, BRICK_SEGS, 0))

    def test_comet_sits_on_the_head_and_inner_lane_stays_quiet_for_bass(self):
        cols, segs = BRICK_COLS, BRICK_SEGS
        mask = [0.0] * (cols * segs)
        bands = [1.0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        fill_orbit_brightness(mask, bands, 1.4, cols, segs)
        outer = orbit_path(cols, segs, 0)
        head = orbit_head_index(len(outer), 0, 1.4)
        c, r = outer[head]
        self.assertGreater(mask[r * cols + c], 0.9)
        lane_max = max(mask[rr * cols + cc] for cc, rr in outer)
        self.assertGreaterEqual(lane_max, mask[r * cols + c] - 1e-9)
        inner = orbit_path(cols, segs, ORBIT_LANES - 1)
        inner_max = max(mask[rr * cols + cc] for cc, rr in inner)
        self.assertLess(inner_max, 0.25)
        self.assertGreater(inner_max, ORBIT_RAIL - 0.001)
        later = [0.0] * (cols * segs)
        fill_orbit_brightness(later, bands, 4.0, cols, segs)
        self.assertNotEqual(
            orbit_head_index(len(outer), 0, 1.4),
            orbit_head_index(len(outer), 0, 4.0),
        )


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
