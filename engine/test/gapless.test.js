import assert from "node:assert/strict";
import { test } from "node:test";
import { setTimeout as delay } from "node:timers/promises";
import { Player } from "../src/player.js";

function track(id) {
  return { id, title: id, artist: "a", duration_secs: 10 };
}

// An mpv stand-in that keeps a playlist the way mpv does: replace, append, clear.
function playlistMpv() {
  const listeners = new Set();
  const mpv = {
    playlist: [],
    pos: -1,
    loads: [],
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
      if (args[0] === "playlist-clear") {
        mpv.playlist = mpv.pos >= 0 ? [mpv.playlist[mpv.pos]] : [];
        mpv.pos = mpv.playlist.length ? 0 : -1;
      }
      return null;
    },
    async pause() {},
    async get() {
      return null;
    },
    async seekAbsolute() {},
    async setVolume() {},
    async setAf() {},
    // mpv reaching the end of the current file on its own
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
    get queued() {
      return mpv.playlist.slice(mpv.pos + 1);
    },
  };
  return mpv;
}

function setup(n = 4) {
  const mpv = playlistMpv();
  const youtube = { streamUrl: async (id) => `mem://${id}` };
  const player = new Player({ mpv, youtube });
  player.replaceQueue(Array.from({ length: n }, (_, i) => track(`t${i + 1}`)), 0);
  return { player, mpv };
}

const settle = () => delay(150);
const loaded = () => delay(450); // the player ignores end-file for 400 ms after a load

test("the next track is queued in mpv right after the current one loads", async () => {
  const { player, mpv } = setup();
  await player.playIndex(0);
  await settle();
  assert.deepEqual(mpv.queued, ["mem://t2"]);
  assert.equal(player.preloaded.id, "t2");
});

test("end of file rolls over without a reload, then queues the one after", async () => {
  const { player, mpv } = setup();
  await player.playIndex(0);
  await loaded();
  mpv.finish();
  await settle();
  assert.equal(player.index, 1);
  assert.equal(player.queue[player.index].id, "t2");
  assert.equal(player.state, "playing");
  assert.deepEqual(mpv.loads, ["mem://t1"], "no loadfile replace at the hand-over");
  assert.deepEqual(mpv.queued, ["mem://t3"]);
});

test("the last track stops at the end like before", async () => {
  const { player, mpv } = setup(2);
  await player.playIndex(1);
  await loaded();
  assert.deepEqual(mpv.queued, []);
  mpv.finish();
  await settle();
  assert.equal(player.state, "stopped");
});

test("repeat one queues the same track, repeat all wraps, shuffled wrap does not preload", async () => {
  const { player, mpv } = setup(3);
  await player.playIndex(2);
  await settle();
  assert.deepEqual(mpv.queued, []);
  player.setRepeat("all");
  await settle();
  assert.deepEqual(mpv.queued, ["mem://t1"]);
  player.setRepeat("one");
  await loaded();
  assert.deepEqual(mpv.queued, ["mem://t3"]);
  mpv.finish();
  await settle();
  assert.equal(player.index, 2);
  player.setRepeat("all");
  player.shuffle = true;
  player.setAutomix("off");
  await settle();
  assert.deepEqual(mpv.queued, [], "a shuffled wrap reshuffles first, so nothing is preloaded");
  assert.equal(player.peekNextIndex(), -1);
});

test("queue edits and shuffle re-sync what mpv has queued", async () => {
  const { player, mpv } = setup(4);
  await player.playIndex(0);
  await settle();
  assert.deepEqual(mpv.queued, ["mem://t2"]);
  player.playNext({ id: "x", title: "x" });
  await settle();
  await settle();
  assert.deepEqual(mpv.queued, ["mem://x"], "the new next is resolved and replaces the stale entry");
  player.move(1, 3);
  await settle();
  assert.deepEqual(mpv.queued, ["mem://t2"]);
  player.removeAt(1);
  await settle();
  assert.equal(mpv.queued.length <= 1, true);
  assert.equal(mpv.queued[0] ? mpv.queued[0] : "", player.preloaded ? `mem://${player.preloaded.id}` : "");
  const orig = Math.random;
  Math.random = () => 0;
  try {
    player.setShuffle("on");
  } finally {
    Math.random = orig;
  }
  await settle();
  const want = player.queue[player.peekNextIndex()]?.id;
  assert.equal(player.preloaded?.id ?? null, player.preloaded ? want : null);
  // a roll-over after edits lands on whatever is next now
  if (player.preloaded) {
    await loaded();
    mpv.finish();
    await settle();
    assert.equal(player.queue[player.index].id, want);
  }
});

test("skip and stop drop the queued entry", async () => {
  const { player, mpv } = setup(4);
  await player.playIndex(0);
  await settle();
  await player.next();
  await settle();
  assert.equal(player.index, 1);
  assert.deepEqual(mpv.loads, ["mem://t1", "mem://t2"]);
  assert.deepEqual(mpv.queued, ["mem://t3"]);
  await player.prev();
  await settle();
  assert.deepEqual(mpv.queued, ["mem://t2"]);
  await player.stop();
  await settle();
  assert.deepEqual(mpv.queued, []);
  assert.equal(player.preloaded, null);
});

test("a queued stream that fails to open is skipped like before", async () => {
  const { player, mpv } = setup(4);
  await player.playIndex(0);
  await loaded();
  mpv.emit({ event: "end-file", reason: "eof" });
  await settle();
  assert.equal(player.index, 1);
  mpv.emit({ event: "end-file", reason: "error" }); // t2's stream would not open
  await settle();
  assert.equal(player.queue[1].playable, false);
  assert.equal(player.index, 2);
  assert.equal(mpv.loads.at(-1), "mem://t3");
});

test("nothing is queued while stopped, so a restore never starts playback", async () => {
  const { player, mpv } = setup(3);
  player.state = "stopped";
  await player.prefetchNext();
  await settle();
  await player.syncPreload();
  assert.deepEqual(mpv.playlist, []);
});
