import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from music_player.engine import EngineSupervisor


class FakeIpc:
    def __init__(self, alive=False):
        self._alive = alive

    def alive(self) -> bool:
        return self._alive


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
