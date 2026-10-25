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
        self.stream: list[dict] | None = None  # set to make "subscribe" answer with these events
        self.hold = False  # keep the subscribe stream open after the events
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
                    if req.get("cmd") == "subscribe" and self.stream is not None:
                        conn.sendall((json.dumps({"ok": True, "subscribed": True, "state": "paused"}) + "\n").encode())
                        for ev in self.stream:
                            time.sleep(0.02)
                            conn.sendall((json.dumps(ev) + "\n").encode())
                        while self.hold and not self._stop.is_set():
                            time.sleep(0.02)
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

    def test_reuses_one_connection_per_lane(self):
        self.server = LineServer()
        self.ipc = EngineIPC(self.server.path, timeout=2)
        self.assertEqual(self.ipc.request({"cmd": "status"})["echo"], "status")
        self.assertEqual(self.ipc.request({"cmd": "bands"})["echo"], "bands")
        self.assertEqual(self.ipc.request({"cmd": "status"})["echo"], "status")
        self.assertEqual(self.server.accepts, 1)
        self.assertEqual(self.ipc.request({"cmd": "search"})["echo"], "search")
        self.assertEqual(self.ipc.request({"cmd": "playlists"})["echo"], "playlists")
        self.assertEqual(self.server.accepts, 2)
        self.assertEqual(self.ipc.request({"cmd": "next"})["echo"], "next")
        self.assertEqual(self.ipc.request({"cmd": "pause"})["echo"], "pause")
        self.assertEqual(self.server.accepts, 3)

    def test_reconnects_after_the_peer_drops(self):
        self.server = LineServer()
        self.ipc = EngineIPC(self.server.path, timeout=2)
        self.assertEqual(self.ipc.request({"cmd": "hello"})["echo"], "hello")
        with self.assertRaises(Exception):
            self.ipc.request({"cmd": "drop"})
        self.assertEqual(self.ipc.request({"cmd": "again"})["echo"], "again")
        self.assertGreaterEqual(self.server.accepts, 2)

    def test_status_is_not_blocked_by_a_slow_query(self):
        self.server = LineServer()
        self.ipc = EngineIPC(self.server.path, timeout=3)
        done = threading.Event()

        def slow() -> None:
            self.ipc.request({"cmd": "search", "delay": 0.45})
            done.set()

        threading.Thread(target=slow, daemon=True).start()
        time.sleep(0.05)
        started = time.monotonic()
        resp = self.ipc.request({"cmd": "status"})
        elapsed = time.monotonic() - started
        self.assertEqual(resp["echo"], "status")
        self.assertLess(elapsed, 0.25)
        self.assertTrue(done.wait(2))
        self.assertGreaterEqual(self.server.accepts, 2)

    def test_one_lane_stays_ordered(self):
        self.server = LineServer()
        self.ipc = EngineIPC(self.server.path, timeout=3)
        out: dict[int, int] = {}

        def worker(n: int) -> None:
            out[n] = self.ipc.request({"cmd": "search", "n": n, "delay": 0.05})["n"]

        threads = [threading.Thread(target=worker, args=(i,)) for i in (1, 2, 3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3)
        self.assertEqual(out, {1: 1, 2: 2, 3: 3})
        self.assertEqual(self.server.accepts, 1)


if __name__ == "__main__":
    unittest.main()


class SubscribeTests(unittest.TestCase):
    def tearDown(self) -> None:
        self.server.close()

    def test_streams_ack_then_events_until_the_engine_hangs_up(self):
        self.server = LineServer()
        self.server.stream = [{"ok": True, "event": "status", "state": "playing"}, {"ok": True, "event": "status", "state": "paused"}]
        got = []
        result = EngineIPC(self.server.path, timeout=2).subscribe(got.append, threading.Event())
        self.assertEqual(result, "closed")
        self.assertEqual([g.get("state") for g in got], ["paused", "playing", "paused"])
        self.assertTrue(got[0]["subscribed"])
        self.assertEqual(got[1]["event"], "status")

    def test_older_engine_is_reported_unsupported(self):
        self.server = LineServer()  # echoes, no "subscribed"
        got = []
        self.assertEqual(EngineIPC(self.server.path, timeout=2).subscribe(got.append, threading.Event()), "unsupported")
        self.assertEqual(got, [])

    def test_stop_ends_an_open_stream(self):
        self.server = LineServer()
        self.server.stream = []
        self.server.hold = True
        stop = threading.Event()
        out = {}
        t = threading.Thread(target=lambda: out.setdefault("r", EngineIPC(self.server.path, timeout=2).subscribe(lambda _e: None, stop)))
        t.start()
        time.sleep(0.2)
        stop.set()
        t.join(2)
        self.assertEqual(out.get("r"), "stopped")

    def test_missing_engine_raises_oserror(self):
        self.server = LineServer()
        with self.assertRaises(OSError):
            EngineIPC(self.server.path + ".missing", timeout=1).subscribe(lambda _e: None, threading.Event())
