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

    def test_no_thumbs_down_control(self):
        self.assertFalse(hasattr(self.win, "btn_dislike"))
        icon = ROOT / "ui" / "music_player" / "icons" / "hicolor" / "scalable" / "actions" / "music-thumb-down-symbolic.svg"
        self.assertFalse(icon.exists())

    def test_clicking_the_vis_cycles_meter_and_field(self):
        from music_player.spectrum import cycle_vis

        self.assertEqual(self.win.spectrum.mode, "bricks")
        self.assertEqual(self.win.field.mode, "bricks")
        self.win._cycle_vis()
        self.assertEqual(self.win.spectrum.mode, "wave")
        self.assertEqual(self.win.field.mode, "wave")
        self.win._cycle_vis()
        self.assertEqual(self.win.spectrum.mode, cycle_vis("wave"))
        self.assertEqual(self.win.field.mode, self.win.spectrum.mode)

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
        self._cfg.write_text('vis_mode = "wave"\n')
        self.win._reload_config()
        self.assertEqual(self.win.spectrum.mode, "wave")

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
