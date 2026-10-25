// Regression tests: removing queue rows while playing, and seeking past the end.
// Nothing here makes sound: the fakes never open audio, and the one real mpv
// runs with --ao=null on a silent file and a private temp socket.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { setTimeout as delay } from "node:timers/promises";
import { Mpv } from "../src/mpv.js";
import { unplayableError } from "../src/playable.js";
import { Player, SEEK_END_MARGIN_S, clampSeek } from "../src/player.js";
import { dispatch } from "../src/server.js";

function track(id, duration_secs = 10) {
  return { id, title: id, artist: "a", duration_secs };
}

// An mpv stand-in with a playlist (replace / append / clear / stop) and sticky pause.
function playlistMpv({ duration = null } = {}) {
  const listeners = new Set();
  const mpv = {
    playlist: [],
    pos: -1,
    loads: [],
    commands: [],
    seeks: [],
    paused: false,
    duration,
    onEvent(fn) {
      listeners.add(fn);
    },
    emit(ev) {
      for (const fn of listeners) fn(ev);
    },
    async load(url) {
      mpv.loads.push(url);
      mpv.playlist = [url];
      mpv.pos = 0;
    },
    async append(url) {
      mpv.playlist.push(url);
    },
    async command(args) {
      mpv.commands.push(args[0]);
      if (args[0] === "playlist-clear") {
        mpv.playlist = mpv.pos >= 0 ? [mpv.playlist[mpv.pos]] : [];
        mpv.pos = mpv.playlist.length ? 0 : -1;
      } else if (args[0] === "stop") {
        mpv.playlist = [];
        mpv.pos = -1;
      }
      return null;
    },
    async pause(p) {
      mpv.paused = Boolean(p);
    },
    async get(prop) {
      if (prop === "duration") return mpv.pos >= 0 ? mpv.duration : null;
      if (prop === "idle-active") return mpv.pos < 0;
      if (prop === "pause") return mpv.paused;
      return null;
    },
    async seekAbsolute(s) {
      mpv.seeks.push(s);
    },
    async setVolume() {},
    async setAf() {},
    finish() {
      mpv.emit({ event: "end-file", reason: "eof" });
      if (mpv.pos + 1 < mpv.playlist.length) {
        mpv.pos += 1;
        mpv.emit({ event: "file-loaded" });
      } else {
        mpv.pos = -1;
        mpv.emit({ event: "idle" });
      }
    },
    get current() {
      return mpv.pos >= 0 ? mpv.playlist[mpv.pos] : null;
    },
    get queued() {
      return mpv.playlist.slice(mpv.pos + 1);
    },
  };
  return mpv;
}

function setup(n = 4, opts = {}) {
  const mpv = playlistMpv(opts);
  const youtube = { streamUrl: async (id) => `mem://${id}` };
  const player = new Player({ mpv, youtube });
  player.replaceQueue(Array.from({ length: n }, (_, i) => track(`t${i + 1}`)), 0);
  return { player, mpv };
}

const settle = () => delay(150);
const loaded = () => delay(450); // the player ignores end-file for 400 ms after a load
const ids = (player) => player.queue.map((t) => t.id);

// ---- bug 1: removing queue rows ----

test("removing the playing row plays the next one and re-preloads", async () => {
  const { player, mpv } = setup(4);
  await player.playIndex(1);
  await settle();
  assert.deepEqual(mpv.queued, ["mem://t3"]);
  await player.removeAt(1);
  assert.deepEqual(ids(player), ["t1", "t3", "t4"]);
  assert.equal(player.index, 1);
  assert.equal(mpv.current, "mem://t3", "the removed song is no longer what mpv plays");
  assert.equal(player.state, "playing");
  assert.equal(mpv.paused, false);
  assert.equal(player.position, 0);
  await settle();
  assert.deepEqual(mpv.queued, ["mem://t4"]);
  assert.equal(player.preloaded.id, "t4");
});

test("removing the playing row while paused loads the next one paused", async () => {
  const { player, mpv } = setup(3);
  await player.playIndex(0);
  await player.pause();
  assert.equal(player.state, "paused");
  await player.removeAt(0);
  assert.equal(player.index, 0);
  assert.equal(player.queue[0].id, "t2");
  assert.equal(mpv.current, "mem://t2");
  assert.equal(player.state, "paused");
  assert.equal(mpv.paused, true, "never unpaused, not even briefly");
  await settle();
  assert.deepEqual(mpv.queued, ["mem://t3"]);
});

test("removing the playing row when it is the last one stops cleanly", async () => {
  const { player, mpv } = setup(3);
  await player.playIndex(2);
  await settle();
  const loadsBefore = mpv.loads.length;
  await player.removeAt(2);
  assert.deepEqual(ids(player), ["t1", "t2"]);
  assert.equal(player.state, "stopped");
  assert.equal(player.index, 1);
  assert.equal(player.position, 0);
  assert.equal(mpv.current, null, "mpv unloaded the removed song");
  assert.deepEqual(mpv.playlist, []);
  assert.equal(mpv.loads.length, loadsBefore, "nothing new was started");
  assert.equal(player.preloaded, null);
  // play afterwards starts the (new) current row, not the removed one
  await player.toggle();
  assert.equal(mpv.current, "mem://t2");
  assert.equal(player.state, "playing");
});

test("removing the only row stops and empties the queue", async () => {
  const { player, mpv } = setup(1);
  await player.playIndex(0);
  await player.removeAt(0);
  assert.equal(player.queue.length, 0);
  assert.equal(player.index, -1);
  assert.equal(player.state, "stopped");
  assert.equal(mpv.current, null);
});

test("removing the last playing row with repeat all wraps to the first", async () => {
  const { player, mpv } = setup(3);
  player.setRepeat("all");
  await player.playIndex(2);
  await player.removeAt(2);
  assert.equal(player.index, 0);
  assert.equal(mpv.current, "mem://t1");
  assert.equal(player.state, "playing");
});

test("removing the playing row skips an unplayable next row", async () => {
  const mpv = playlistMpv();
  const youtube = {
    streamUrl: async (id) => {
      if (id === "t2") {
        throw unplayableError("test");
      }
      return `mem://${id}`;
    },
  };
  const player = new Player({ mpv, youtube });
  player.replaceQueue([track("t1"), track("t2"), track("t3")], 0);
  await player.playIndex(0);
  await player.removeAt(0);
  assert.deepEqual(ids(player), ["t2", "t3"]);
  assert.equal(player.queue[0].playable, false);
  assert.equal(player.index, 1);
  assert.equal(mpv.current, "mem://t3");
  assert.equal(player.state, "playing");
});

test("removing a row while stopped does not start playback", async () => {
  const { player, mpv } = setup(3);
  await player.removeAt(0);
  assert.equal(player.state, "stopped");
  assert.equal(mpv.loads.length, 0);
  assert.deepEqual(mpv.playlist, []);
  assert.equal(player.queue[player.index].id, "t2");
});

test("removing the row right after the playing one drops the preloaded entry at once", async () => {
  const { player, mpv } = setup(4);
  await player.playIndex(0);
  await settle();
  assert.deepEqual(mpv.queued, ["mem://t2"]);
  await player.removeAt(1);
  assert.equal(mpv.current, "mem://t1", "the playing track is untouched");
  assert.equal(mpv.queued.includes("mem://t2"), false, "no debounce window with the removed entry queued");
  await settle();
  await settle();
  assert.deepEqual(mpv.queued, ["mem://t3"]);
  assert.deepEqual(player.preloaded, { id: "t3", url: "mem://t3", index: 1 });
  await loaded();
  mpv.finish();
  await settle();
  assert.equal(player.queue[player.index].id, "t3");
  assert.equal(mpv.current, "mem://t3");
  assert.deepEqual(mpv.loads, ["mem://t1"], "still a gapless hand-over");
});

test("the removed next row is cleared from mpv even when the new next is not resolved yet", async () => {
  const { player, mpv } = setup(4);
  let release;
  const gate = new Promise((r) => {
    release = r;
  });
  await player.playIndex(0);
  await settle();
  assert.deepEqual(mpv.queued, ["mem://t2"]);
  const orig = player.youtube.streamUrl;
  player.youtube.streamUrl = async (id) => {
    if (id === "t3") await gate;
    return orig(id);
  };
  await player.removeAt(1);
  assert.deepEqual(mpv.queued, [], "stale entry gone while t3 still resolves");
  release();
  await settle();
  await settle();
  assert.deepEqual(mpv.queued, ["mem://t3"]);
});

test("end of file right after removing the next row never plays the removed track", async () => {
  const { player, mpv } = setup(4);
  await player.playIndex(0);
  await loaded();
  assert.deepEqual(mpv.queued, ["mem://t2"]);
  // hand-over races the removal: mpv still had t2 queued when the file ended
  const removal = player.removeAt(1);
  mpv.finish();
  await removal;
  await settle();
  assert.equal(player.queue[player.index].id, "t3");
  assert.equal(mpv.current, "mem://t3");
});

test("removing a row before the playing one keeps the preloaded entry", async () => {
  const { player, mpv } = setup(4);
  await player.playIndex(2);
  await settle();
  assert.deepEqual(mpv.queued, ["mem://t4"]);
  const commandsBefore = mpv.commands.length;
  await player.removeAt(0);
  assert.equal(player.index, 1);
  assert.equal(mpv.current, "mem://t3");
  assert.deepEqual(player.preloaded, { id: "t4", url: "mem://t4", index: 2 });
  await settle();
  assert.deepEqual(mpv.queued, ["mem://t4"]);
  assert.equal(mpv.commands.length, commandsBefore, "no needless playlist churn");
  await loaded();
  mpv.finish();
  await settle();
  assert.equal(player.queue[player.index].id, "t4");
  assert.deepEqual(mpv.loads, ["mem://t3"]);
});

test("removing a row further down leaves playback and the preload alone", async () => {
  const { player, mpv } = setup(4);
  await player.playIndex(0);
  await settle();
  await player.removeAt(3);
  assert.equal(mpv.current, "mem://t1");
  assert.deepEqual(mpv.queued, ["mem://t2"]);
  assert.equal(player.state, "playing");
});

test("queue.remove over the protocol waits for the hand-over", async () => {
  const { player, mpv } = setup(3);
  await player.playIndex(0);
  const resp = await dispatch(player, {}, { cmd: "queue.remove", index: 0 });
  assert.equal(resp.ok, true);
  assert.equal(resp.index, 0);
  assert.deepEqual(resp.tracks.map((t) => t.id), ["t2", "t3"]);
  assert.equal(mpv.current, "mem://t2");
});

test("removeAt still rejects bad indexes", async () => {
  const { player } = setup(2);
  await assert.rejects(() => player.removeAt(5), /out of range/);
  await assert.rejects(() => player.removeAt(-1), /out of range/);
  await assert.rejects(() => player.removeAt("x"), /out of range/);
});

// ---- bug 2: seeking past the end ----

test("clampSeek keeps targets inside [0, duration - margin]", () => {
  assert.equal(SEEK_END_MARGIN_S, 1);
  assert.equal(clampSeek(500, 200), 199);
  assert.equal(clampSeek(200, 200), 199);
  assert.equal(clampSeek(199.5, 200), 199);
  assert.equal(clampSeek(50, 200), 50);
  assert.equal(clampSeek(-3, 200), 0);
  assert.equal(clampSeek(Number.NaN, 200), 0);
  assert.equal(clampSeek("12", 200), 12);
  assert.equal(clampSeek(5, 0.5), 0, "a sub-second track clamps to its start");
  assert.equal(clampSeek(90, 0), 90, "unknown duration: no upper clamp");
});

test("seeking past the end clamps to just before it (mpv duration)", async () => {
  const { player, mpv } = setup(3, { duration: 180.5 });
  await player.playIndex(0);
  await loaded();
  await player.seek(10_000);
  assert.deepEqual(mpv.seeks, [179.5]);
  assert.equal(player.position, 179.5);
  assert.equal(player.index, 0, "no skip");
  assert.equal(mpv.current, "mem://t1");
  await player.seek(-20);
  assert.deepEqual(mpv.seeks, [179.5, 0]);
});

test("seeking past the end falls back to the queue duration when mpv has none", async () => {
  const { player, mpv } = setup(3);
  await player.playIndex(0);
  await player.seek(11);
  assert.deepEqual(mpv.seeks, [9]);
  assert.equal(player.index, 0);
});

test("a seek while stopped is clamped too (resume target)", async () => {
  const { player, mpv } = setup(2);
  await player.seek(1e6);
  assert.equal(player.position, 9);
  assert.deepEqual(mpv.seeks, [9]);
});

test("after a clamped seek the natural end still rolls over gaplessly", async () => {
  const { player, mpv } = setup(3, { duration: 10 });
  await player.playIndex(0);
  await loaded();
  await player.seek(60);
  assert.equal(player.index, 0);
  await settle();
  mpv.finish();
  await settle();
  assert.equal(player.index, 1);
  assert.equal(mpv.current, "mem://t2");
  assert.deepEqual(mpv.loads, ["mem://t1"], "no reload at the hand-over");
});

// ---- end to end on a real, silent, isolated mpv ----

function silentWav(dir, name, seconds) {
  const file = path.join(dir, name);
  const made = spawnSync(
    "ffmpeg",
    ["-y", "-loglevel", "error", "-f", "lavfi", "-i", `anullsrc=r=44100:cl=stereo`, "-t", String(seconds), file],
    { encoding: "utf8" },
  );
  assert.equal(made.status, 0, made.stderr);
  return file;
}

test("real mpv: seek past the end stays on the track; removing current advances", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "mp-queue-seek-"));
  const files = { a: silentWav(dir, "a.wav", 4), b: silentWav(dir, "b.wav", 4), c: silentWav(dir, "c.wav", 4) };
  // private socket in a temp dir, null audio output, and volume 0 for good measure
  const mpv = new Mpv(path.join(dir, "mpv.sock"), { extraArgs: ["--ao=null", "--volume=0"] });
  await mpv.start();
  try {
    const player = new Player({ mpv, youtube: { streamUrl: async (id) => files[id] } });
    player.replaceQueue([track("a", 4), track("b", 4), track("c", 4)], 0);
    await player.playIndex(0);
    await delay(500);
    await player.seek(100);
    await delay(400);
    assert.equal(player.index, 0, "seeking past the end did not skip");
    const pos = await mpv.get("time-pos");
    assert.ok(pos != null && pos >= 2.5 && pos < 4, `expected just before the end, got ${pos}`);
    // the natural end (about a second later) still advances
    const deadline = Date.now() + 4000;
    while (player.index === 0 && Date.now() < deadline) {
      await delay(50);
    }
    assert.equal(player.index, 1, "natural end advanced to the next track");
    await delay(200);
    // removing the playing row loads the next one in mpv
    await player.removeAt(1);
    await delay(300);
    assert.equal(player.queue[player.index].id, "c");
    assert.equal(await mpv.get("path"), files.c);
    // removing the last (playing) row stops: mpv goes idle
    await player.removeAt(1);
    await delay(200);
    assert.equal(player.state, "stopped");
    assert.equal(await mpv.get("idle-active"), true);
  } finally {
    await mpv.quit();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
