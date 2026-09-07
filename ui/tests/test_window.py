import unittest
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, GLib, Gtk

from music_player.ipc import EngineIPC
from music_player.window import EQ_LABELS, WINDOW_H, PlayerWindow


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
        self.win = PlayerWindow(self.app, FakeIpc())
        self.cmds = []
        self.win._queue_cmd = lambda payload, timeout=20.0: self.cmds.append(payload)

    def tearDown(self):
        self.win.stop_pump()

    def _key(self, keyval, *, ctrl=False) -> bool:
        state = Gdk.ModifierType.CONTROL_MASK if ctrl else 0
        return bool(self.win._on_key(None, keyval, 0, state))

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

    def test_eq_fold_is_hidden_and_independent_of_body_mode(self):
        self.assertEqual(len(EQ_LABELS), 10)
        self.assertFalse(self.win.eq_revealer.get_reveal_child())
        self.assertFalse(self.win.btn_mode_eq.get_active())
        self.win.btn_mode_eq.set_active(True)
        self.assertTrue(self.win.eq_revealer.get_reveal_child())
        self.assertEqual(self.win.body_stack.get_visible_child_name(), "queue")
        self.win.btn_mode_eq.set_active(False)
        self.assertFalse(self.win.eq_revealer.get_reveal_child())

    def test_header_has_no_shade_control(self):
        self.assertFalse(hasattr(self.win, "btn_shade"))
        self.assertTrue(self.win.body_box.get_visible())
        self.assertEqual(self.win.track_title.get_text(), "Nothing playing")
        self.assertIsNotNone(self.win.spectrum)
        _w, h = self.win.get_default_size()
        self.assertEqual(h, WINDOW_H)

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
        self.assertTrue(self._key(Gdk.KEY_e))
        self.assertTrue(self.win.eq_revealer.get_reveal_child())

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


class CompactSizeTests(unittest.TestCase):
    def test_hypr_rules_use_full_player_size(self):
        text = (ROOT / "packaging" / "hypr-window-rules.conf").read_text()
        self.assertIn("920, 720", text)
        self.assertNotIn("shade", text.lower())
        self.assertNotIn("80", text)

    def test_bar_raise_locks_full_player_size(self):
        text = (ROOT / "packaging" / "llurd.music" / "BarWidget.qml").read_text()
        self.assertIn('min_size\\", value = \\"920 720\\"', text)
        self.assertNotIn('920 80', text)


if __name__ == "__main__":
    unittest.main()
