import unittest

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk

from music_player.layout import caption_bar, make_row
from music_player.library import LibraryMixin
from music_player.login import LoginMixin
from music_player.window import PlayerWindow, bind_ellipsize, constrain_scroll


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
