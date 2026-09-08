import unittest

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk

from music_player.layout import caption_bar, deck_scale, deck_size, make_row
from music_player.library import LibraryMixin
from music_player.login import LoginMixin
from music_player.window import PlayerWindow, bind_ellipsize, constrain_scroll


class DeckScaleTests(unittest.TestCase):
    def test_about_one_on_1080p(self):
        scale = deck_scale(1920, 1080)
        self.assertGreaterEqual(scale, 0.9)
        self.assertLessEqual(scale, 1.2)

    def test_grows_on_a_large_panel_but_caps(self):
        small = deck_scale(1920, 1080)
        large = deck_scale(3840, 1600)
        self.assertGreater(large, small)
        self.assertLessEqual(large, 1.5)
        w, h = deck_size(3840, 1600)
        self.assertGreater(w, 1180)
        self.assertGreater(h, 800)

    def test_shrinks_on_a_small_panel(self):
        scale = deck_scale(1366, 768)
        self.assertLess(scale, 1.0)
        self.assertGreaterEqual(scale, 0.75)


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
