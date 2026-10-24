import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from music_player.app import default_socket
from music_player.engine import EngineSupervisor


class FakeIpc:
    def __init__(self, alive=False):
        self._alive = alive

    def alive(self) -> bool:
        return self._alive


class DefaultSocketTests(unittest.TestCase):
    def test_music_player_sock_overrides_xdg_config_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            sock = str(Path(tmp) / "isolated.sock")
            xdg = str(Path(tmp) / "xdg")
            env = {
                "MUSIC_PLAYER_SOCK": sock,
                "XDG_CONFIG_HOME": xdg,
            }
            with patch.dict(os.environ, env, clear=False):
                self.assertEqual(default_socket(), Path(sock))

    def test_xdg_config_home_is_used_when_sock_is_unset(self):
        with tempfile.TemporaryDirectory() as tmp:
            xdg = str(Path(tmp) / "xdg")
            env = {"XDG_CONFIG_HOME": xdg}
            with patch.dict(os.environ, env, clear=False):
                os.environ.pop("MUSIC_PLAYER_SOCK", None)
                self.assertEqual(
                    default_socket(),
                    Path(xdg) / "music-player" / "engine.sock",
                )


class EngineSupervisorTests(unittest.TestCase):
    def test_existing_pid_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            sock = Path(tmp) / "engine.sock"
            sock.with_name(sock.name + ".pid").write_text(f"{os.getpid()}\n")
            sup = EngineSupervisor(binary="node", socket_path=str(sock), ipc=FakeIpc())
            self.assertEqual(sup._existing_engine_pid(), os.getpid())

    def test_dead_pidfile_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            sock = Path(tmp) / "engine.sock"
            sock.with_name(sock.name + ".pid").write_text("1000000007\n")
            sup = EngineSupervisor(binary="node", socket_path=str(sock), ipc=FakeIpc())
            self.assertEqual(sup._existing_engine_pid(), 0)

    def test_shutdown_kills_orphan_mpv_when_engine_is_dead(self):
        with tempfile.TemporaryDirectory() as tmp:
            sock = Path(tmp) / "engine.sock"
            ipc = FakeIpc(alive=False)
            ipc.request = lambda *a, **k: (_ for _ in ()).throw(OSError("down"))
            sup = EngineSupervisor(binary="node", socket_path=str(sock), ipc=ipc)
            with patch.object(sup, "_kill_orphan_mpv") as kill_mpv:
                with patch.object(sup, "_kill_pidfile"):
                    sup.shutdown()
                    kill_mpv.assert_called_once()

    def test_ensure_points_the_child_at_the_supervisor_socket(self):
        with tempfile.TemporaryDirectory() as tmp:
            sock = str(Path(tmp) / "engine.sock")
            ipc = FakeIpc(alive=False)
            calls = {"n": 0}

            def alive():
                calls["n"] += 1
                return calls["n"] > 1

            ipc.alive = alive
            captured = {}

            def fake_popen(*_a, **kwargs):
                captured["kwargs"] = kwargs

                class Proc:
                    def poll(self):
                        return None

                return Proc()

            with patch("subprocess.Popen", side_effect=fake_popen):
                with patch.dict(os.environ, {"MUSIC_PLAYER_SOCK": "/not/the/supervisor.sock"}, clear=False):
                    EngineSupervisor(binary="node", socket_path=sock, ipc=ipc).ensure()
            env = captured["kwargs"]["env"]
            self.assertEqual(env["MUSIC_PLAYER_SOCK"], sock)
            self.assertIs(captured["kwargs"].get("stderr"), subprocess.PIPE)

    def test_ensure_reports_stderr_when_the_engine_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            sock = str(Path(tmp) / "engine.sock")
            ipc = FakeIpc(alive=False)

            class Err:
                def __init__(self):
                    self._lines = [b"boom: missing module\n", b""]

                def readline(self):
                    return self._lines.pop(0) if self._lines else b""

            class Proc:
                def __init__(self):
                    self.stderr = Err()

                def poll(self):
                    return 1

            sup = EngineSupervisor(binary="node", socket_path=sock, ipc=ipc)
            with patch("subprocess.Popen", return_value=Proc()):
                with self.assertRaises(RuntimeError) as caught:
                    sup.ensure(timeout=1)
            self.assertIn("boom: missing module", str(caught.exception))

    def test_activate_presents_the_window_before_ensure(self):
        from music_player.app import MusicApplication

        order: list[str] = []
        window = type("Win", (), {})()
        window.present = lambda: order.append("present")
        window.connect = lambda *_a: None
        gate = threading.Event()

        class Sup:
            def ensure(self):
                order.append("ensure")
                gate.set()

        app = MusicApplication()
        with patch("music_player.app.PlayerWindow", return_value=window):
            with patch("music_player.app.EngineSupervisor", return_value=Sup()):
                with patch("music_player.app.EngineIPC"):
                    app.do_activate()
        self.assertTrue(gate.wait(2))
        self.assertEqual(order, ["present", "ensure"])

    def test_ensure_waits_instead_of_spawning_when_peer_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            sock = Path(tmp) / "engine.sock"
            sock.with_name(sock.name + ".pid").write_text(f"{os.getpid()}\n")
            ipc = FakeIpc(alive=False)
            sup = EngineSupervisor(binary="node", socket_path=str(sock), ipc=ipc)
            with patch.object(sup, "_wait_ready", return_value=True) as wait:
                with patch("subprocess.Popen") as popen:
                    self.assertTrue(sup.ensure())
                    popen.assert_not_called()
                    wait.assert_called_once()


if __name__ == "__main__":
    unittest.main()
