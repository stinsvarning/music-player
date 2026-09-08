import unittest

from music_player.theme import (
    FALLBACK,
    boost_accent,
    css_for,
    load_omarchy_palette_text,
    mix_hex,
    omarchy_colors_path,
    omarchy_colors_paths,
    palette_from_colors,
    saturation,
    with_accent,
)


AETHER_LIKE = """
background = "#060114"
foreground = "#d7dbe9"
accent = "#757b9d"
selection_background = "#D7DBE9"
"""


class OmarchyPaletteTests(unittest.TestCase):
    def test_maps_aether_like_toml_without_using_light_selection_as_row_fill(self):
        palette = load_omarchy_palette_text(AETHER_LIKE)
        self.assertEqual(palette.name, "omarchy")
        self.assertEqual(palette.bg.lower(), "#060114")
        self.assertEqual(palette.fg.lower(), "#d7dbe9")
        self.assertEqual(palette.accent.lower(), "#757b9d")
        self.assertNotEqual(palette.highlight.lower(), "#d7dbe9")

    def test_partial_toml_uses_fallback_slots(self):
        palette = load_omarchy_palette_text("background = \"#111111\"\nforeground = \"#eeeeee\"\n")
        self.assertEqual(palette.bg, "#111111")
        self.assertEqual(palette.fg, "#eeeeee")
        self.assertTrue(palette.accent.startswith("#"))

    def test_empty_toml_is_usable_fallback(self):
        palette = load_omarchy_palette_text("")
        self.assertEqual(palette.bg, FALLBACK.bg)
        self.assertEqual(palette.fg, FALLBACK.fg)

    def test_select_shade_differs_from_playing_highlight(self):
        select = mix_hex(FALLBACK.bg, FALLBACK.muted, 0.45)
        self.assertNotEqual(select.lower(), FALLBACK.highlight.lower())

    def test_default_path(self):
        self.assertTrue(str(omarchy_colors_path()).endswith("state/omarchy/current/theme/colors.toml"))

    def test_quattro_path_is_tried_before_legacy_config(self):
        paths = [str(p) for p in omarchy_colors_paths()]
        self.assertTrue(paths[0].endswith("state/omarchy/current/theme/colors.toml"))
        self.assertTrue(any(p.endswith(".config/omarchy/current/theme/colors.toml") for p in paths))

    def test_bright_selection_is_not_used_as_highlight(self):
        palette = palette_from_colors(
            {
                "background": "#060114",
                "foreground": "#eeeeee",
                "accent": "#757b9d",
                "selection_background": "#D7DBE9",
            }
        )
        self.assertNotEqual(palette.highlight.lower(), "#d7dbe9")

    def test_boost_accent_lifts_gray_lilac(self):
        raw = "#757b9d"
        boosted = boost_accent(raw)
        self.assertNotEqual(boosted.lower(), raw)
        self.assertGreater(saturation(boosted), saturation(raw))

    def test_palette_does_not_boost_theme_accent(self):
        palette = palette_from_colors(
            {
                "background": "#060114",
                "foreground": "#d7dbe9",
                "accent": "#757b9d",
                "muted": "#66656b",
                "lighter_bg": "#1f1a2c",
                "orange": "#ab9cb6",
            }
        )
        self.assertEqual(palette.accent.lower(), "#757b9d")
        self.assertEqual(palette.bg.lower(), "#060114")
        self.assertEqual(palette.fg.lower(), "#d7dbe9")
        self.assertEqual(palette.muted.lower(), "#66656b")
        self.assertEqual(palette.panel.lower(), "#1f1a2c")
        self.assertEqual(palette.peak.lower(), "#ab9cb6")

    def test_with_accent_retints_highlight(self):
        tinted = with_accent(FALLBACK, "#cc3344")
        self.assertEqual(tinted.accent.lower(), "#cc3344")
        self.assertNotEqual(tinted.highlight.lower(), FALLBACK.highlight.lower())

    def test_css_has_tab_caption_and_search(self):
        css = css_for(FALLBACK)
        self.assertIn(".tab-caption", css)
        self.assertIn(".lcd", css)
        self.assertIn(".marquee", css)
        self.assertIn(".deck", css)
        self.assertIn(".stage", css)
        self.assertIn("button.seg", css)
        self.assertIn(".tab-page", css)
        self.assertNotIn("lyric-now", css)
        self.assertIn("row.unplayable", css)

    def test_css_keeps_design_type_size(self):
        css = css_for(FALLBACK)
        self.assertIn("font-size: 36px", css)
        self.assertNotIn("font-size: 54px", css)

    def test_css_square_window_matches_hypr(self):
        css = css_for(FALLBACK)
        self.assertIn("border-radius: 0", css)
        self.assertNotIn("ghost-head", css)

    def test_css_top_and_bottom_rails_share_size(self):
        css = css_for(FALLBACK)
        self.assertIn(".deck-bar, .foot", css)
        self.assertIn("min-height: 40px", css)


if __name__ == "__main__":
    unittest.main()
