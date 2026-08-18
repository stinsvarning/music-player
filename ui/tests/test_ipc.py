import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from music_player.ipc import EngineIPC


class LineServer:
    def __init__(self):
        self.dir = tempfile.mkdtemp()
        self.path = str(Path(self.dir) / "engine.sock")
        self.accepts = 0
        self._stop = threading.Event()
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(self.path)
        self._sock.listen(8)
        self._sock.settimeout(0.2)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            self.accepts += 1
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _client(self, conn: socket.socket) -> None:
        buf = b""
        conn.settimeout(2)
        try:
            while not self._stop.is_set():
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    req = json.loads(line.decode())
                    if req.get("cmd") == "drop":
                        conn.close()
                        return
                    time.sleep(float(req.get("delay") or 0))
                    resp = {"ok": True, "echo": req.get("cmd"), "n": req.get("n")}
                    conn.sendall((json.dumps(resp) + "\n").encode())
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def close(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass


class EngineIPCTests(unittest.TestCase):
    def tearDown(self) -> None:
        if hasattr(self, "server"):
            self.server.close()
        if hasattr(self, "ipc"):
            self.ipc.close()

    def test_reuses_one_connection_across_requests(self):
        self.server = LineServer()
        self.ipc = EngineIPC(self.server.path, timeout=2)
        self.assertEqual(self.ipc.request({"cmd": "a"})["echo"], "a")
        self.assertEqual(self.ipc.request({"cmd": "b"})["echo"], "b")
        self.assertEqual(self.ipc.request({"cmd": "c"})["echo"], "c")
        self.assertEqual(self.server.accepts, 1)

    def test_reconnects_after_the_peer_drops(self):
        self.server = LineServer()
        self.ipc = EngineIPC(self.server.path, timeout=2)
        self.assertEqual(self.ipc.request({"cmd": "hello"})["echo"], "hello")
        with self.assertRaises(Exception):
            self.ipc.request({"cmd": "drop"})
        self.assertEqual(self.ipc.request({"cmd": "again"})["echo"], "again")
        self.assertGreaterEqual(self.server.accepts, 2)

    def test_serializes_concurrent_requests(self):
        self.server = LineServer()
        self.ipc = EngineIPC(self.server.path, timeout=3)
        out: dict[int, int] = {}

        def worker(n: int) -> None:
            out[n] = self.ipc.request({"cmd": "echo", "n": n, "delay": 0.05})["n"]

        threads = [threading.Thread(target=worker, args=(i,)) for i in (1, 2, 3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3)
        self.assertEqual(out, {1: 1, 2: 2, 3: 3})
        self.assertEqual(self.server.accepts, 1)


if __name__ == "__main__":
    unittest.main()
