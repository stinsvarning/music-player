import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, GLib, Gtk

from music_player.ipc import EngineIPC
from music_player.window import WINDOW_H, PlayerWindow


ROOT = Path(__file__).resolve().parents[2]


class FakeIpc(EngineIPC):
    def __init__(self):
        super().__init__("/tmp/music-player-test-missing.sock", timeout=0.1)

    def request(self, payload, *, timeout=None, raise_on_error=True):
        return {"ok": True, "state": "stopped", "position": 0, "duration": 0, "volume": 70}


class WindowChromeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        display = Gdk.Display.get_default()
        if display is None:
            raise unittest.SkipTest("GTK display required")
        cls.app = Gtk.Application(application_id="stream.music.Player.windowtest")
        cls.app.register()

    def setUp(self):
        self._cfg = Path(tempfile.mkdtemp()) / "config.toml"
        self._old_cfg = os.environ.get("MUSIC_PLAYER_CONFIG")
        os.environ["MUSIC_PLAYER_CONFIG"] = str(self._cfg)
        self.win = PlayerWindow(self.app, FakeIpc())
        self.cmds = []
        self.win._queue_cmd = lambda payload, timeout=20.0: self.cmds.append(payload)

    def tearDown(self):
        self.win.stop_pump()
        if self._old_cfg is None:
            os.environ.pop("MUSIC_PLAYER_CONFIG", None)
        else:
            os.environ["MUSIC_PLAYER_CONFIG"] = self._old_cfg

    def _key(self, keyval, *, ctrl=False) -> bool:
        state = Gdk.ModifierType.CONTROL_MASK if ctrl else 0
        return bool(self.win._on_key(None, keyval, 0, state))

    def test_chrome_wording(self):
        from music_player.models import PlayerStatus, playback_word

        self.assertEqual(self.win.btn_account.get_label(), "Account")
        self.assertEqual(self.win.search_entry.get_placeholder_text(), "title or artist")
        self.assertEqual(self.win.status_label.get_text(), "stopped")
        self.win.status = PlayerStatus(state="paused")
        self.win._apply_status()
        self.assertEqual(self.win.status_label.get_text(), playback_word("paused"))
        self.win.status = PlayerStatus(state="playing")
        self.win._apply_status()
        self.assertEqual(self.win.status_label.get_text(), "playing")

    def test_queue_and_library_share_two_columns(self):
        self.assertTrue(self.win.queue_scroll.get_parent().get_hexpand())
        self.assertTrue(self.win.lyrics_scroll.get_parent().get_hexpand())
        self.assertTrue(self.win.playlist_list.get_parent().get_parent().get_hexpand())
        self.assertTrue(self.win.track_list.get_parent().get_parent().get_hexpand())

    def test_queue_and_library_are_exclusive_body_modes(self):
        self.assertEqual(self.win.body_stack.get_visible_child_name(), "queue")
        self.assertTrue(self.win.btn_mode_queue.get_active())
        self.assertFalse(self.win.btn_mode_library.get_active())
        self.win._show_library()
        self.assertEqual(self.win.body_stack.get_visible_child_name(), "library")
        self.assertTrue(self.win.btn_mode_library.get_active())
        self.assertFalse(self.win.btn_mode_queue.get_active())
        self.win._show_queue()
        self.assertEqual(self.win.body_stack.get_visible_child_name(), "queue")

    def test_no_eq_fold_or_shade(self):
        self.assertFalse(hasattr(self.win, "eq_revealer"))
        self.assertFalse(hasattr(self.win, "btn_mode_eq"))
        self.assertFalse(hasattr(self.win, "btn_shade"))
        self.assertTrue(self.win.body_box.get_visible())
        self.assertEqual(self.win.track_title.get_text(), "Nothing playing")
        self.assertIsNotNone(self.win.spectrum)
        self.assertTrue(self.win.deck.has_css_class("deck"))
        self.assertIsNotNone(self.win.field)
        _w, h = self.win.get_default_size()
        self.assertEqual(h, WINDOW_H)

    def test_find_row_has_no_slash_chip(self):
        bar = self.win.search_entry.get_parent()
        child = bar.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Label) and child.get_text() == "/":
                self.fail("slash find chip is still in the chrome")
            child = child.get_next_sibling()

    def test_transport_buttons_are_marked(self):
        for btn in (
            self.win.btn_prev,
            self.win.btn_play,
            self.win.btn_stop,
            self.win.btn_next,
            self.win.btn_shuf,
            self.win.btn_auto,
            self.win.btn_sleep,
        ):
            self.assertTrue(bool(btn.get_icon_name()) or bool(btn.get_label()), btn.get_tooltip_text())

    def test_deck_width_does_not_follow_the_title(self):
        req_w, _req_h = self.win.deck.get_size_request()
        before = self.win.deck.measure(Gtk.Orientation.HORIZONTAL, -1).natural
        self.win.track_title.set_text("Very Long Song Title " * 12)
        after = self.win.deck.measure(Gtk.Orientation.HORIZONTAL, -1).natural
        self.assertLessEqual(after, req_w + 24)
        self.assertLessEqual(abs(after - before), 24)

    def test_deck_stays_at_design_size(self):
        from music_player.layout import DECK_FRAME
        from music_player.window import DECK_H, DECK_W

        self.assertEqual(self.win.deck.get_size_request(), (DECK_W + DECK_FRAME, DECK_H + DECK_FRAME))
        self.assertEqual((DECK_W, DECK_H), (1180, 800))
        self.assertFalse(hasattr(self.win, "_fit_deck"))

    def test_deck_shrinks_in_small_tiles_and_returns_to_design_size(self):
        from music_player.layout import DECK_FRAME
        from music_player.window import DECK_H, DECK_W

        self.win._on_stage_resize(None, 1280, 640)
        self.win._apply_deck_mode()
        self.assertEqual(self.win.deck.get_size_request(), (DECK_W + DECK_FRAME, 600))
        self.assertIn("deck-compact", self.win.deck.get_css_classes())
        self.win._on_stage_resize(None, 720, 540)
        self.win._apply_deck_mode()
        self.assertEqual(self.win.deck.get_size_request(), (720, 540))
        self.assertIn("deck-narrow", self.win.deck.get_css_classes())
        self.assertFalse(self.win.vol_lab.get_visible())
        self.win._on_stage_resize(None, 3840, 1600)
        self.win._apply_deck_mode()
        self.assertEqual(self.win.deck.get_size_request(), (DECK_W + DECK_FRAME, DECK_H + DECK_FRAME))
        self.assertNotIn("deck-compact", self.win.deck.get_css_classes())
        self.assertNotIn("deck-narrow", self.win.deck.get_css_classes())
        self.assertTrue(self.win.vol_lab.get_visible())
        self.assertEqual(self.win.transport_box.get_spacing(), 10)

    def test_window_uses_hypr_chrome_not_gtk_csd(self):
        self.assertIsNone(self.win.get_titlebar())
        self.assertFalse(self.win.get_decorated())

    def test_lcd_does_not_show_or_fetch_cover_art(self):
        self.assertFalse(hasattr(self.win, "art"))
        self.assertFalse(hasattr(self.win, "_load_art"))
        pictures = []

        def walk(widget):
            if isinstance(widget, Gtk.Picture):
                pictures.append(widget)
            child = widget.get_first_child()
            while child is not None:
                walk(child)
                child = child.get_next_sibling()

        walk(self.win.deck)
        self.assertEqual(pictures, [])

    def test_lyrics_column_is_plain_text(self):
        self.win._show_lyrics(["first line", "second line"], found=True)
        self.assertTrue(self.win.lyrics_list.get_visible())
        self.assertFalse(self.win.lyrics_empty.get_visible())
        row = self.win.lyrics_list.get_row_at_index(0)
        label = row.get_child()
        self.assertEqual(label.get_text(), "first line")
        self.assertTrue(label.has_css_class("lyric-line"))
        self.assertFalse(label.has_css_class("lyric-now"))
        self.assertEqual(self.win.lyrics_list.get_row_at_index(1).get_child().get_text(), "second line")
        self.win._show_lyrics([], found=False)
        self.assertFalse(self.win.lyrics_list.get_visible())
        self.assertEqual(self.win.lyrics_empty.get_text(), "no lyrics")

    def test_footer_keeps_progress_across_a_status_tick(self):
        from music_player.models import PlayerStatus

        self.win._set_footer("searching weezer…")
        self.assertEqual(self.win.status_label.get_text(), "searching weezer…")
        self.assertTrue(self.win.status_label.has_css_class("foot-progress"))
        self.win.status = PlayerStatus(state="playing")
        self.win._apply_status()
        self.assertEqual(self.win.status_label.get_text(), "searching weezer…")
        self.win._set_footer("could not search")
        self.assertTrue(self.win.status_label.has_css_class("foot-error"))
        self.win._set_footer("offline")
        self.assertEqual(self.win.status_label.get_text(), "offline")
        self.assertTrue(self.win.status_label.has_css_class("foot-offline"))

    def test_question_mark_toggles_the_key_card(self):
        self.assertFalse(self.win._help_veil.get_visible())
        self.assertTrue(self._key(Gdk.KEY_question))
        self.assertTrue(self.win._help_veil.get_visible())
        labels = []
        card = self.win._help_veil.get_first_child()
        child = card.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Label):
                labels.append(child.get_text())
            child = child.get_next_sibling()
        self.assertTrue(any("delete" in line for line in labels))
        self.assertTrue(self._key(Gdk.KEY_Escape))
        self.assertFalse(self.win._help_veil.get_visible())

    def test_delete_removes_the_selected_queue_row(self):
        from music_player.models import Track

        self.win._queue = [Track(id="a", title="A"), Track(id="b", title="B")]
        self.win._render_queue(self.win._queue, 0)
        row = self.win.queue_list.get_row_at_index(1)
        self.win.queue_list.select_row(row)
        self.cmds.clear()
        self.assertTrue(self._key(Gdk.KEY_Delete))
        self.assertEqual(self.cmds[-1], {"cmd": "queue.remove", "index": 1})

    def _queue_of(self, n, current=0):
        from music_player.models import Track

        tracks = [Track(id=f"t{i}", title=f"T{i}") for i in range(n)]
        self.win.status.index = current
        self.win._render_queue(tracks, current)
        return tracks

    def _row_titles(self):
        out = []
        row = self.win.queue_list.get_first_child()
        while row is not None:
            texts = []
            stack = [row]
            while stack:
                w = stack.pop()
                if isinstance(w, Gtk.Label):
                    texts.append(w.get_text())
                c = w.get_last_child()
                while c is not None:
                    stack.append(c)
                    c = c.get_prev_sibling()
            out.append(texts[0] if texts else "")
            row = row.get_next_sibling()
        return out

    def _current_rows(self):
        out, i = [], 0
        row = self.win.queue_list.get_first_child()
        while row is not None:
            if row.has_css_class("current-track"):
                out.append(i)
            i += 1
            row = row.get_next_sibling()
        return out

    def test_alt_down_moves_the_selected_row_and_the_selection_follows(self):
        self._queue_of(4, current=0)
        self.win.queue_list.select_row(self.win.queue_list.get_row_at_index(1))
        self.cmds.clear()
        vol = self.win.volume.get_value()
        state = Gdk.ModifierType.ALT_MASK
        self.assertTrue(self.win._on_key(None, Gdk.KEY_Down, 0, state))
        self.assertEqual(self.cmds[-1], {"cmd": "queue.move", "from": 1, "to": 2})
        self.assertEqual([t.id for t in self.win._queue], ["t0", "t2", "t1", "t3"])
        self.assertEqual(self.win.queue_list.get_selected_row().get_index(), 2)
        self.assertTrue(self.win._on_key(None, Gdk.KEY_Up, 0, state))
        self.assertTrue(self.win._on_key(None, Gdk.KEY_Up, 0, state))
        self.assertEqual(self.cmds[-1], {"cmd": "queue.move", "from": 1, "to": 0})
        self.assertEqual([t.id for t in self.win._queue], ["t1", "t0", "t2", "t3"])
        self.assertEqual(self.win.queue_list.get_selected_row().get_index(), 0)
        self.assertEqual(self._current_rows(), [1], "the playing marker follows the playing row")
        self.assertEqual(self.win.volume.get_value(), vol, "alt+arrows never touch the volume")

    def test_alt_up_on_the_first_row_does_nothing(self):
        self._queue_of(3)
        self.win.queue_list.select_row(self.win.queue_list.get_row_at_index(0))
        self.cmds.clear()
        self.assertTrue(self.win._on_key(None, Gdk.KEY_Up, 0, Gdk.ModifierType.ALT_MASK))
        self.assertEqual(self.cmds, [])

    def test_moved_rows_are_redrawn_in_the_new_order(self):
        self._queue_of(4, current=2)
        self.win._move_queue_row(0, 3)
        titles = self._row_titles()
        self.assertTrue(titles[0].endswith("T1") and titles[3].endswith("T0"), titles)
        self.assertTrue(titles[0].startswith("01"), "row numbers follow the new order")
        self.assertEqual(self._current_rows(), [1])

    def _menu_labels(self):
        out = []
        stack = [self.win._ctx_pop]
        while stack:
            w = stack.pop()
            if isinstance(w, Gtk.Button) and w.get_label():
                out.append(w.get_label())
            c = w.get_last_child()
            while c is not None:
                stack.append(c)
                c = c.get_prev_sibling()
        return out

    def _click_menu(self, label):
        stack = [self.win._ctx_pop]
        while stack:
            w = stack.pop()
            if isinstance(w, Gtk.Button) and w.get_label() == label:
                w.emit("clicked")
                return
            c = w.get_last_child()
            while c is not None:
                stack.append(c)
                c = c.get_prev_sibling()
        self.fail(f"no {label} in {self._menu_labels()}")

    def test_queue_menu_play_next_and_move_to_top_bottom(self):
        tracks = self._queue_of(5, current=1)
        row = self.win.queue_list.get_row_at_index(4)
        self.win._popup_song_menu(row, tracks[4], "queue")
        self.assertIn("Play next", self._menu_labels())
        self.cmds.clear()
        self._click_menu("Play next")
        self.assertEqual(self.cmds[-1], {"cmd": "queue.move", "from": 4, "to": 2})
        self.assertEqual([t.id for t in self.win._queue], ["t0", "t1", "t4", "t2", "t3"])
        row = self.win.queue_list.get_row_at_index(3)
        self.win._popup_song_menu(row, self.win._queue[3], "queue")
        self._click_menu("Move to top")
        self.assertEqual(self.cmds[-1], {"cmd": "queue.move", "from": 3, "to": 0})
        self.assertEqual(self.win.status.index, 2)
        row = self.win.queue_list.get_row_at_index(0)
        self.win._popup_song_menu(row, self.win._queue[0], "queue")
        self.assertNotIn("Move to top", self._menu_labels())
        self._click_menu("Move to bottom")
        self.assertEqual(self.cmds[-1], {"cmd": "queue.move", "from": 0, "to": 4})
        self.assertEqual(self.win.queue_list.get_selected_row().get_index(), 4)

    def test_ctrl_z_sends_undo(self):
        self.cmds.clear()
        self.assertTrue(self._key(Gdk.KEY_z, ctrl=True))
        self.assertEqual(self.cmds[-1], {"cmd": "queue.undo"})

    def test_ctrl_z_in_the_find_box_stays_with_the_entry(self):
        self.win.search_entry.has_focus = lambda: True  # a headless window never gets real focus
        self.cmds.clear()
        self.assertFalse(self._key(Gdk.KEY_z, ctrl=True))
        self.assertEqual(self.cmds, [])

    def test_undoable_edits_show_a_quiet_undo_note(self):
        self.assertFalse(self.win.undo_note.get_visible())
        self.win._after_queue_edit("queue.remove", {"ok": True})
        self.assertTrue(self.win.undo_note.get_visible())
        self.assertEqual(self.win.undo_label.get_text(), "Removed ·")
        self.assertEqual(self.win.undo_button.get_label(), "Undo")
        self.win._after_queue_edit("track.mix", {"ok": True})
        self.assertEqual(self.win.undo_label.get_text(), "Mix started ·")
        self.win._after_queue_edit("queue.clear_upcoming", {"ok": True, "removed": 4})
        self.assertEqual(self.win.undo_label.get_text(), "Cleared upcoming ·")
        self.cmds.clear()
        self.win.undo_button.emit("clicked")
        self.assertEqual(self.cmds[-1], {"cmd": "queue.undo"})
        self.assertFalse(self.win.undo_note.get_visible())

    def test_the_undo_note_fades_away(self):
        from music_player import footer

        self.win._after_queue_edit("queue.remove", {"ok": True})
        self.assertTrue(self.win._undo_hold)
        GLib.source_remove(self.win._undo_hold)
        self.win._undo_hold = 0
        old = footer.UNDO_FADE_MS
        footer.UNDO_FADE_MS = 80
        try:
            self.win._fade_undo_note()
            ctx = GLib.MainContext.default()
            deadline = time.monotonic() + 2
            while self.win.undo_note.get_visible() and time.monotonic() < deadline:
                ctx.iteration(False)
                time.sleep(0.01)
        finally:
            footer.UNDO_FADE_MS = old
        self.assertFalse(self.win.undo_note.get_visible())

    def test_clearing_nothing_and_undo_are_plain_notes(self):
        self.win._after_queue_edit("queue.clear_upcoming", {"ok": True, "removed": 0})
        self.assertFalse(self.win.undo_note.get_visible())
        self.assertEqual(self.win.status_label.get_text(), "nothing after this track")
        self.win._after_queue_edit("queue.undo", {"ok": True, "undone": "Removed"})
        self.assertEqual(self.win.status_label.get_text(), "undone")
        self.assertTrue(self.win.status_label.has_css_class("foot-note"))

    def test_queue_menu_clear_upcoming(self):
        tracks = self._queue_of(4, current=1)
        self.win._popup_song_menu(self.win.queue_list.get_row_at_index(0), tracks[0], "queue")
        self.cmds.clear()
        self._click_menu("Clear upcoming")
        self.assertEqual(self.cmds[-1], {"cmd": "queue.clear_upcoming"})

    def _row_y(self, index):
        row = self.win.queue_list.get_row_at_index(index)
        ok, b = row.compute_bounds(self.win.queue_list)
        return b.get_y() + b.get_height() / 2

    def _drop_classes(self):
        out = []
        for i in range(len(self.win._queue)):
            row = self.win.queue_list.get_row_at_index(i)
            for name in ("drop-above", "drop-below"):
                if row.has_css_class(name):
                    out.append((i, name))
        return out

    def _realize(self):
        self.win.present()
        ctx = GLib.MainContext.default()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            ctx.iteration(False)
            row = self.win.queue_list.get_row_at_index(0)
            if row is not None and row.get_height() > 0:
                return
        self.skipTest("rows never got a size")

    def test_dragging_shows_a_thin_drop_line_where_the_row_lands(self):
        self._queue_of(5, current=0)
        self._realize()
        self.win._on_drag_prepare(self.win.queue_list.get_row_at_index(1))
        self.win._on_queue_drag_motion(None, 10, self._row_y(3))
        self.assertEqual(self._drop_classes(), [(3, "drop-below")], "moving down lands after row 3")
        self.win._on_queue_drag_motion(None, 10, self._row_y(1))
        self.assertEqual(self._drop_classes(), [], "no line over the row itself")
        self.win._on_drag_prepare(self.win.queue_list.get_row_at_index(4))
        self.win._on_queue_drag_motion(None, 10, self._row_y(0))
        self.assertEqual(self._drop_classes(), [(0, "drop-above")], "moving up lands before row 0")
        self.cmds.clear()
        self.assertTrue(self.win._on_queue_drop(None, "4", 10, self._row_y(0)))
        self.assertEqual(self.cmds[-1], {"cmd": "queue.move", "from": 4, "to": 0})
        self.assertEqual(self._drop_classes(), [], "the line goes away on drop")
        self.assertEqual(self.win.queue_list.get_selected_row().get_index(), 0, "selection follows the dropped row")
        self.assertEqual([t.id for t in self.win._queue], ["t4", "t0", "t1", "t2", "t3"])

    def test_leaving_the_list_clears_the_drop_line(self):
        self._queue_of(3)
        self._realize()
        self.win._on_drag_prepare(self.win.queue_list.get_row_at_index(0))
        self.win._on_queue_drag_motion(None, 10, self._row_y(2))
        self.assertTrue(self._drop_classes())
        self.win._clear_drop_line()
        self.assertEqual(self._drop_classes(), [])

    def test_right_click_selects_the_row_first(self):
        tracks = self._queue_of(4, current=0)
        self.win.queue_list.select_row(self.win.queue_list.get_row_at_index(0))
        row = self.win.queue_list.get_row_at_index(2)
        self.win._show_song_menu(row, tracks[2], "queue", Gtk.GestureClick())
        self.assertEqual(self.win.queue_list.get_selected_row().get_index(), 2)
        self.win._dismiss_menu()
        self.cmds.clear()
        self.assertTrue(self._key(Gdk.KEY_Delete))
        self.assertEqual(self.cmds[-1], {"cmd": "queue.remove", "index": 2})

    def test_focus_does_not_start_on_the_account_link(self):
        self.win.set_focus(self.win.btn_account)
        self.win._initial_focus()
        self.assertIsNot(self.win.get_focus(), self.win.btn_account)
        self.win.set_focus(None)
        self.win._initial_focus()
        focus = self.win.get_focus()
        if focus is not None:
            self.assertTrue(self.win._queue_has_focus())

    def test_copy_link_puts_the_music_link_on_the_clipboard(self):
        from music_player.models import Track

        track = Track(id="RE_XX6jk2Lo", title="Beyond", artist="Daft Punk")
        self.win._copy_link(track)
        clip = self.win.get_clipboard()
        self.assertTrue(clip.is_local())
        got = []
        clip.read_text_async(None, lambda c, res: got.append(c.read_text_finish(res)))
        ctx = GLib.MainContext.default()
        deadline = time.monotonic() + 2
        while not got and time.monotonic() < deadline:
            ctx.iteration(False)
            time.sleep(0.01)
        self.assertEqual(got, ["https://music.youtube.com/watch?v=RE_XX6jk2Lo"])
        self.assertEqual(self.win.status_label.get_text(), "link copied")

    def test_go_to_artist_and_album_search_the_library(self):
        from music_player.models import Track

        track = Track(id="v", title="Voyager", artist="Daft Punk", album="Discovery")
        self.win._queue = [track]
        self.win._render_queue([track], 0)
        sent = []
        self.win.ipc.request = lambda payload, **_k: sent.append(payload) or {"ok": True, "tracks": []}
        self.win._popup_song_menu(self.win.queue_list.get_row_at_index(0), track, "queue")
        self._click_menu("Go to artist")
        self.assertEqual(self.win.body_stack.get_visible_child_name(), "library")
        self.assertEqual(self.win.search_entry.get_text(), "Daft Punk")
        self.win._popup_song_menu(self.win.queue_list.get_row_at_index(0), track, "queue")
        self._click_menu("Go to album")
        self.assertEqual(self.win.search_entry.get_text(), "Discovery Daft Punk")
        ctx = GLib.MainContext.default()
        deadline = time.monotonic() + 2
        while len(sent) < 2 and time.monotonic() < deadline:
            ctx.iteration(False)
            time.sleep(0.01)
        self.assertIn({"cmd": "search", "query": "Discovery Daft Punk"}, sent)

    def test_song_menus_have_thin_rules_between_sections(self):
        tracks = self._queue_of(4, current=0)
        self.win._popup_song_menu(self.win.queue_list.get_row_at_index(2), tracks[2], "queue")
        rules = []
        stack = [self.win._ctx_pop]
        while stack:
            w = stack.pop()
            if isinstance(w, Gtk.Separator):
                rules.append(w)
            c = w.get_first_child()
            while c is not None:
                stack.append(c)
                c = c.get_next_sibling()
        self.assertEqual(len(rules), 3)
        self.assertTrue(all(r.has_css_class("ctx-rule") for r in rules))

    def test_key_card_lists_queue_moves(self):
        from music_player.keys import HELP_LINES

        self.assertTrue(any(line.startswith("alt+up") for line in HELP_LINES))
        self.assertTrue(any(line.startswith("ctrl+z") for line in HELP_LINES))

    def test_no_thumbs_down_control(self):
        self.assertFalse(hasattr(self.win, "btn_dislike"))
        icon = ROOT / "ui" / "music_player" / "icons" / "hicolor" / "scalable" / "actions" / "music-thumb-down-symbolic.svg"
        self.assertFalse(icon.exists())

    def test_clicking_the_vis_cycles_meter_and_field(self):
        self.assertEqual(self.win.spectrum.mode, "bricks")
        self.assertEqual(self.win.field.mode, "bricks")
        seen = []
        for _ in range(4):
            self.win._cycle_vis()
            self.assertEqual(self.win.field.mode, self.win.spectrum.mode)
            seen.append(self.win.spectrum.mode)
        self.assertEqual(seen, ["wave", "waterfall", "off", "bricks"])
        # each click is remembered by the engine (session.json), not written to config.toml
        self.assertEqual([c for c in self.cmds if c["cmd"] == "vis"], [{"cmd": "vis", "mode": m} for m in seen])
        self.assertFalse(self._cfg.exists())

    def test_off_stops_band_polling_and_on_resumes_it(self):
        self.win._apply_vis("off")
        self.assertFalse(self.win._bands_wanted)
        self.win._on_status({"ok": True, "state": "playing", "position": 0, "duration": 100, "volume": 50})
        self.win.spectrum.queue_draw = lambda: self.fail("off must not redraw on bands")
        self.win._on_bands({"ok": True, "bands": [0.9] * 10})
        del self.win.spectrum.queue_draw
        self.win._apply_vis("wave")
        self.assertTrue(self.win._bands_wanted)
        self.win._on_bands({"ok": True, "bands": [0.9] * 10})
        self.assertTrue(self.win.spectrum._awake)

    def test_engine_analysis_follows_the_window(self):
        base = {"ok": True, "state": "playing", "position": 0, "duration": 100, "volume": 50}
        self.win._apply_vis("off")  # e.g. vis_mode = "off" in config on a first run
        self.win._on_status({**base, "vis_mode": None, "vis_on": True})
        self.assertEqual(self.cmds[-1], {"cmd": "vis", "mode": "off", "save": False})
        n = len(self.cmds)
        self.win._on_status({**base, "vis_mode": None, "vis_on": True})
        self.assertEqual(len(self.cmds), n)  # asked once, not on every status
        self.win._on_status({**base, "vis_mode": None, "vis_on": False})
        self.assertEqual(len(self.cmds), n)
        # a look chosen elsewhere (music-player-ctl vis wave) shows up here
        self.win._on_status({**base, "vis_mode": "wave", "vis_on": True})
        self.assertEqual(self.win.spectrum.mode, "wave")
        self.assertEqual(self.win.field.mode, "wave")
        self.assertEqual(len(self.cmds), n)
        # an older engine without the keys is left alone
        self.win._on_status(base)
        self.assertEqual(self.win.spectrum.mode, "wave")

    def test_a_status_from_before_a_click_does_not_undo_it(self):
        base = {"ok": True, "state": "playing", "position": 0, "duration": 100, "volume": 50}
        self.win._on_status({**base, "vis_mode": "bricks", "vis_on": True})
        self.win._cycle_vis()
        self.win._on_status({**base, "vis_mode": "bricks", "vis_on": True})
        self.assertEqual(self.win.spectrum.mode, "wave")

    def test_volume_scales_the_visualizers(self):
        from music_player.spectrum import volume_intensity

        self.win.volume.set_value(20)
        self.assertAlmostEqual(self.win.spectrum.state.intensity, volume_intensity(20))
        self.assertAlmostEqual(self.win.field.state.intensity, volume_intensity(20))
        self.win._on_status({"ok": True, "state": "playing", "position": 0, "duration": 0, "volume": 100})
        self.assertAlmostEqual(self.win.spectrum.state.intensity, 1.0)
        self.assertAlmostEqual(self.win.field.state.intensity, 1.0)

    def test_pushed_status_drives_the_clock_between_updates(self):
        base = {"ok": True, "event": "status", "duration": 200, "volume": 50, "track": {"id": "t1", "title": "One"}}
        self.win._on_status({**base, "state": "playing", "position": 10.0})
        self.assertTrue(self.win._playing_hint)
        self.assertTrue(self.win._pos_timer)
        self.assertEqual(self.win.track_title.get_text(), "One")
        self.win._pos_base = (10.0, time.monotonic() - 3.0)
        self.assertTrue(self.win._tick_position())
        self.assertEqual(self.win.pos_label.get_text(), "0:13")
        self.win._on_status({**base, "state": "paused", "position": 14.0})
        self.assertFalse(self.win._playing_hint)
        self.assertEqual(self.win._pos_timer, 0)

    def test_hand_edited_vis_mode_applies_live(self):
        self._cfg.write_text('vis_mode = "orbit"\n')
        self.win._reload_config()
        self.assertEqual(self.win.spectrum.mode, "waterfall")
        self.assertEqual(self.win.field.mode, "waterfall")
        self.assertEqual(self.cmds[-1], {"cmd": "vis", "mode": "waterfall"})  # becomes the saved choice
        self._cfg.write_text('vis_mode = "off"\n')
        self.win._reload_config()
        self.assertEqual(self.win.spectrum.mode, "off")
        self.assertEqual(self.cmds[-1], {"cmd": "vis", "mode": "off"})
        self._cfg.write_text('vis_mode = "wave"\n')
        self.win._reload_config()
        self.assertEqual(self.win.spectrum.mode, "wave")

    def test_other_config_edits_keep_the_clicked_look(self):
        self._cfg.write_text('vis_mode = "wave"\n')
        self.win._reload_config()
        self.win._cycle_vis()  # waterfall, saved by the engine
        n = len(self.cmds)
        self._cfg.write_text('vis_mode = "wave"\naccent = "#ff0000"\n')
        self.win._reload_config()
        self.assertEqual(self.win.spectrum.mode, "waterfall")
        self.assertEqual(len(self.cmds), n)

    def test_login_card_lists_browsers_on_this_computer(self):
        self.win._fill_login_browsers(
            [
                {"id": "zen", "label": "Zen", "spec": "firefox:~/.config/zen", "desktop": ["zen"], "bins": ["zen-browser"]},
                {"id": "brave", "label": "Brave", "spec": "brave:~/.config/BraveSoftware/Brave-Browser", "desktop": ["brave-browser"], "bins": ["brave"]},
            ]
        )
        labels = []
        child = self.win.login_browser_box.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Button):
                labels.append(child.get_label())
            child = child.get_next_sibling()
        self.assertEqual(labels, ["Sign in with Zen", "Sign in with Brave"])

    def test_top_and_bottom_rails_are_the_same_height(self):
        top = self.win.deck.get_first_child()
        foot = self.win.deck.get_last_child()
        self.assertTrue(top.has_css_class("deck-bar"))
        self.assertTrue(foot.has_css_class("foot"))
        top_h = top.measure(Gtk.Orientation.VERTICAL, -1).natural
        foot_h = foot.measure(Gtk.Orientation.VERTICAL, -1).natural
        self.assertEqual(top_h, foot_h)

    def test_seek_keys_and_slider_never_seek_past_the_end(self):
        from music_player.models import PlayerStatus

        self.win.status = PlayerStatus(state="playing", position=178.0, duration=180.0)
        self.cmds.clear()
        self.assertTrue(self._key(Gdk.KEY_Right))
        self.assertEqual(self.cmds[-1], {"cmd": "seek", "value": 179.0})
        self.win.status = PlayerStatus(state="playing", position=2.0, duration=180.0)
        self.assertTrue(self._key(Gdk.KEY_Left))
        self.assertEqual(self.cmds[-1], {"cmd": "seek", "value": 0.0})
        # slider dragged all the way to the end
        self.cmds.clear()
        self.win._seek.drag(180.0)
        self.win._commit_seek(immediate=True)
        self.assertEqual(self.cmds[-1], {"cmd": "seek", "value": 179.0})

    def test_window_keys_are_handled(self):
        keys = [
            (Gdk.KEY_space, False, {"cmd": "toggle"}),
            (Gdk.KEY_n, False, {"cmd": "next"}),
            (Gdk.KEY_p, False, {"cmd": "prev"}),
            (Gdk.KEY_s, False, {"cmd": "stop"}),
        ]
        for keyval, ctrl, expect in keys:
            self.cmds.clear()
            self.assertTrue(self._key(keyval, ctrl=ctrl), msg=keyval)
            self.assertEqual(self.cmds[-1], expect)

        vol = self.win.volume.get_value()
        self.assertTrue(self._key(Gdk.KEY_Up))
        self.assertGreater(self.win.volume.get_value(), vol)
        self.assertTrue(self._key(Gdk.KEY_Down))

        self.cmds.clear()
        self.assertTrue(self._key(Gdk.KEY_Left))
        self.assertEqual(self.cmds[-1]["cmd"], "seek")
        self.assertTrue(self._key(Gdk.KEY_Right))

        self.assertTrue(self._key(Gdk.KEY_l))
        self.assertTrue(self._key(Gdk.KEY_q))
        self.assertEqual(self.win.body_stack.get_visible_child_name(), "queue")
        self.assertTrue(self._key(Gdk.KEY_m))
        self.assertEqual(self.win.body_stack.get_visible_child_name(), "library")
        self.assertTrue(self._key(Gdk.KEY_F11))

        self.win.present()
        ctx = GLib.MainContext.default()
        for _ in range(40):
            if not ctx.iteration(False):
                break
        self.assertTrue(self._key(Gdk.KEY_f, ctrl=True))
        for _ in range(20):
            ctx.iteration(False)
        focused = self.win.get_focus()
        delegate = self.win.search_entry.get_delegate()
        self.assertIn(focused, (self.win.search_entry, delegate))
        self.assertTrue(self._key(Gdk.KEY_Escape))
        for _ in range(20):
            ctx.iteration(False)
        self.assertNotIn(self.win.get_focus(), (self.win.search_entry, delegate))
        self.win.set_visible(False)

        quits = []
        self.app.quit_engine = lambda: quits.append(True)
        self.assertTrue(self._key(Gdk.KEY_q, ctrl=True))
        self.assertEqual(quits, [True])

    def test_status_keeps_polling_during_a_slow_command(self):
        started = threading.Event()
        release = threading.Event()
        seen: list[str] = []
        lock = threading.Lock()

        def request(payload, *, timeout=None, raise_on_error=True):
            cmd = str(payload.get("cmd") or "")
            if cmd == "track.play":
                started.set()
                release.wait(1.5)
            with lock:
                seen.append(cmd)
            return {"ok": True, "state": "stopped", "position": 0, "duration": 0, "volume": 70}

        self.win.ipc.request = request
        self.win._bootstrap = lambda: False
        try:
            self.win._on_map()
            deadline = time.time() + 1.0
            while time.time() < deadline:
                with lock:
                    if "status" in seen:
                        break
                time.sleep(0.02)
            else:
                self.fail("status pump did not start")
            with lock:
                seen.clear()
            self.win._queue_cmd = PlayerWindow._queue_cmd.__get__(self.win, PlayerWindow)
            self.win._queue_cmd({"cmd": "track.play", "track": {"id": "abc"}}, timeout=5)
            self.assertTrue(started.wait(1.0), "play did not start")
            with lock:
                seen.clear()
            deadline = time.time() + 1.0
            while time.time() < deadline:
                with lock:
                    if "status" in seen:
                        return
                time.sleep(0.02)
            self.fail("status stalled behind track.play")
        finally:
            release.set()


class CompactSizeTests(unittest.TestCase):
    def test_hypr_rules_fill_the_monitor(self):
        text = (ROOT / "packaging" / "hypr-window-rules.conf").read_text()
        self.assertIn("music", text)
        self.assertNotIn("920, 720", text)
        self.assertNotIn("shade", text.lower())

    def test_readme_matches_the_current_app(self):
        text = (ROOT / "README.md").read_text()
        self.assertNotIn("equalizer.png", text.lower())
        self.assertNotIn("920×720", text)
        self.assertNotIn("920x720", text)
        self.assertIn("bricks", text.lower())
        self.assertIn("Sign in with", text)

    def test_bar_raise_maximizes(self):
        text = (ROOT / "packaging" / "llurd.music" / "BarWidget.qml").read_text()
        self.assertIn("maximized", text)
        self.assertNotIn("920 720", text)


if __name__ == "__main__":
    unittest.main()
