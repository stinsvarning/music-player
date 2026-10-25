import unittest

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk

import music_player.layout as layout
from music_player.layout import caption_bar, make_row
from music_player.library import LibraryMixin
from music_player.login import LoginMixin
from music_player.window import DECK_H, DECK_W, PlayerWindow, bind_ellipsize, constrain_scroll


class DeckSizeTests(unittest.TestCase):
    def test_layout_does_not_scale_the_card_to_the_monitor(self):
        self.assertFalse(hasattr(layout, "deck_scale"))
        self.assertFalse(hasattr(layout, "deck_size"))
        self.assertEqual((DECK_W, DECK_H), (1180, 800))

    def test_big_windows_keep_the_exact_design_card(self):
        full = (DECK_W + layout.DECK_FRAME, DECK_H + layout.DECK_FRAME)
        for size in ((3840, 1600), (7680, 4320), (1920, 1600), (1900, 1080), (1232, 852)):
            fit = layout.fit_deck(*size)
            self.assertEqual((fit.width, fit.height), full, size)
            self.assertFalse(fit.compact or fit.narrow, size)

    def test_smaller_tiles_shrink_with_a_margin_then_fill(self):
        fit = layout.fit_deck(1900, 800)
        self.assertEqual((fit.width, fit.height), (1182, 752))
        self.assertFalse(fit.compact)
        fit = layout.fit_deck(1920, 640)
        self.assertEqual(fit.height, 600)
        self.assertTrue(fit.compact)
        fit = layout.fit_deck(960, 1080)
        self.assertEqual(fit.width, 912)
        self.assertFalse(fit.narrow)
        fit = layout.fit_deck(720, 540)
        self.assertEqual((fit.width, fit.height), (720, 540))
        self.assertTrue(fit.compact and fit.narrow)

    def test_fit_never_exceeds_the_window_or_the_design(self):
        for w in range(300, 4000, 97):
            for h in range(200, 2000, 89):
                fit = layout.fit_deck(w, h)
                self.assertLessEqual(fit.width, min(w, DECK_W + layout.DECK_FRAME))
                self.assertLessEqual(fit.height, min(h, DECK_H + layout.DECK_FRAME))


class EllipsizeWidthTests(unittest.TestCase):
    def test_long_title_does_not_request_thousands_of_pixels(self):
        raw = Gtk.Label(label=("Very Long Playlist Title " * 20).strip())
        raw_nat = raw.measure(Gtk.Orientation.HORIZONTAL, -1).natural
        capped = Gtk.Label(label=("Very Long Playlist Title " * 20).strip())
        bind_ellipsize(capped, 36)
        cap_nat = capped.measure(Gtk.Orientation.HORIZONTAL, -1).natural
        self.assertGreater(raw_nat, 1500)
        self.assertLess(cap_nat, 500)

    def test_list_row_inside_scroll_stays_narrow(self):
        win = Gtk.Window()
        scroll = constrain_scroll(Gtk.ScrolledWindow())
        listing = Gtk.ListBox()
        listing.append(PlayerWindow._row(None, "Liked Music — " + ("x" * 200), "ytmusic", "128"))
        listing.append(PlayerWindow._row(None, "01  " + ("Long Track Title " * 15), "Some Artist Name", "3:25"))
        scroll.set_child(listing)
        win.set_child(scroll)
        win.set_default_size(920, 720)
        nat = scroll.measure(Gtk.Orientation.HORIZONTAL, -1).natural
        win.destroy()
        self.assertLess(nat, 920)


class WindowSplitTests(unittest.TestCase):
    def test_player_window_uses_login_and_library_mixins(self):
        self.assertTrue(issubclass(PlayerWindow, LoginMixin))
        self.assertTrue(issubclass(PlayerWindow, LibraryMixin))

    def test_row_helper_matches_window_row(self):
        via_layout = make_row("Title", "mid", "1")
        via_window = PlayerWindow._row(None, "Title", "mid", "1")
        self.assertEqual(type(via_layout).__name__, type(via_window).__name__)

    def test_caption_bar_is_two_equal_columns(self):
        bar, left, right = caption_bar()
        self.assertTrue(bar.has_css_class("tab-caption"))
        self.assertTrue(left.get_hexpand())
        self.assertTrue(right.get_hexpand())
        self.assertIs(bar.get_first_child(), left)
        self.assertIs(left.get_next_sibling(), right)


if __name__ == "__main__":
    unittest.main()
