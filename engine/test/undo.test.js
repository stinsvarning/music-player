// Undo for queue edits (remove, mix, clear upcoming) and the clear-upcoming command.
// Nothing here makes sound: the mpv stand-in never opens audio.
import assert from "node:assert/strict";
import { test } from "node:test";
import { setTimeout as delay } from "node:timers/promises";
import { Player, UNDO_LIMIT } from "../src/player.js";
import { dispatch } from "../src/server.js";
import { parseCtlArgs } from "../src/ctl.js";

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
      if (prop === "time-pos") return mpv.pos >= 0 ? mpv.timePos : null;
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


function mixYoutube(player, tracks) {
  player.youtube.mix = async () => ({ tracks });
}

test("undo after removing a later row restores it without touching playback", async () => {
  const { player, mpv } = setup(4);
  await player.playIndex(1);
  await settle();
  const loads = mpv.loads.length;
  await player.removeAt(3);
  assert.equal(player.undoLabel, "Removed");
  const res = await player.undo();
  assert.equal(res.label, "Removed");
  assert.deepEqual(ids(player), ["t1", "t2", "t3", "t4"]);
  assert.equal(player.index, 1);
  assert.equal(mpv.loads.length, loads, "the playing song was never reloaded");
  assert.equal(player.undoLabel, null);
});

test("undo after removing a row above the playing one keeps the index on the same song", async () => {
  const { player, mpv } = setup(4);
  await player.playIndex(2);
  await settle();
  await player.removeAt(0);
  assert.equal(player.index, 1);
  await player.undo();
  assert.equal(player.index, 2);
  assert.equal(player.queue[2].id, "t3");
  assert.equal(mpv.current, "mem://t3");
  await settle();
  assert.deepEqual(mpv.queued, ["mem://t4"], "the gapless entry matches the restored queue");
});

test("undo after removing the playing row brings that song back where it was", async () => {
  const { player, mpv } = setup(4);
  await player.playIndex(1);
  await loaded();
  mpv.timePos = 42.5;
  await player.removeAt(1);
  assert.equal(mpv.current, "mem://t3");
  mpv.seeks.length = 0;
  await player.undo();
  assert.deepEqual(ids(player), ["t1", "t2", "t3", "t4"]);
  assert.equal(player.index, 1);
  assert.equal(mpv.current, "mem://t2");
  assert.equal(player.state, "playing");
  assert.deepEqual(mpv.seeks, [42.5], "resumes at the position it had");
});

test("undo while paused keeps it paused", async () => {
  const { player, mpv } = setup(3);
  await player.playIndex(0);
  await player.pause();
  await player.removeAt(0);
  await player.undo();
  assert.equal(player.state, "paused");
  assert.equal(mpv.current, "mem://t1");
  assert.equal(mpv.paused, true);
});

test("undo a mix restores the old queue, song and position", async () => {
  const { player, mpv } = setup(4);
  mixYoutube(player, [track("m1"), track("m2"), track("m3")]);
  await player.playIndex(2);
  await loaded();
  mpv.timePos = 61;
  player.automix = false;
  await player.startMix(track("m1"));
  assert.deepEqual(ids(player), ["m1", "m2", "m3"]);
  assert.equal(player.automix, true);
  assert.equal(player.undoLabel, "Mix started");
  mpv.seeks.length = 0;
  await player.undo();
  assert.deepEqual(ids(player), ["t1", "t2", "t3", "t4"]);
  assert.equal(player.index, 2);
  assert.equal(mpv.current, "mem://t3");
  assert.deepEqual(mpv.seeks, [61]);
  assert.equal(player.automix, false, "play-similar goes back to how it was");
});

test("undo a mix started from the playing song leaves it playing", async () => {
  const { player, mpv } = setup(3);
  mixYoutube(player, [track("t2"), track("m2")]);
  await player.playIndex(1);
  await player.startMix(track("t2"));
  const loads = mpv.loads.length;
  await player.undo();
  assert.deepEqual(ids(player), ["t1", "t2", "t3"]);
  assert.equal(player.index, 1);
  assert.equal(mpv.loads.length, loads, "no reload");
});

test("clear upcoming drops rows after the current one and can be undone", async () => {
  const { player, mpv } = setup(5);
  await player.playIndex(1);
  await settle();
  assert.deepEqual(mpv.queued, ["mem://t3"]);
  const removed = await player.clearUpcoming();
  assert.equal(removed, 3);
  assert.deepEqual(ids(player), ["t1", "t2"]);
  assert.equal(player.index, 1);
  assert.deepEqual(mpv.queued, [], "nothing stale left for a gapless hand-over");
  assert.equal(mpv.current, "mem://t2");
  await player.undo();
  assert.deepEqual(ids(player), ["t1", "t2", "t3", "t4", "t5"]);
  assert.equal(player.index, 1);
  await settle();
  assert.deepEqual(mpv.queued, ["mem://t3"]);
});

test("clear upcoming on the last row is a no-op and adds no undo step", async () => {
  const { player } = setup(2);
  await player.playIndex(1);
  assert.equal(await player.clearUpcoming(), 0);
  assert.equal(player.undoLabel, null);
});

test("undo keeps the song you moved on to when the action did not touch it", async () => {
  const { player, mpv } = setup(5);
  await player.playIndex(0);
  await player.removeAt(4);
  await player.next(); // now on t2
  const loads = mpv.loads.length;
  await player.undo();
  assert.deepEqual(ids(player), ["t1", "t2", "t3", "t4", "t5"]);
  assert.equal(player.queue[player.index].id, "t2");
  assert.equal(mpv.loads.length, loads);
});

test("undo while stopped restores the queue without starting playback", async () => {
  const { player, mpv } = setup(3);
  await player.removeAt(0);
  await player.undo();
  assert.deepEqual(ids(player), ["t1", "t2", "t3"]);
  assert.equal(player.state, "stopped");
  assert.equal(mpv.loads.length, 0);
});

test("the undo stack keeps the last ten steps, newest first", async () => {
  const { player } = setup(14);
  for (let i = 0; i < 12; i += 1) {
    await player.removeAt(0);
  }
  let n = 0;
  while (player.undoLabel) {
    await player.undo();
    n += 1;
  }
  assert.equal(n, UNDO_LIMIT);
  assert.equal(player.queue.length, 2 + UNDO_LIMIT);
  assert.equal(player.queue[0].id, "t3", "the two oldest removals fell off the stack");
  await assert.rejects(() => player.undo(), /nothing to undo/);
});

test("queue.clear_upcoming and queue.undo over the protocol and ctl", async () => {
  const { player } = setup(4);
  await player.playIndex(0);
  let resp = await dispatch(player, {}, { cmd: "queue.clear_upcoming" });
  assert.equal(resp.ok, true);
  assert.equal(resp.removed, 3);
  assert.equal(resp.undo, "Cleared upcoming");
  resp = await dispatch(player, {}, { cmd: "queue.list" });
  assert.equal(resp.undo, "Cleared upcoming");
  resp = await dispatch(player, {}, { cmd: "queue.undo" });
  assert.equal(resp.undone, "Cleared upcoming");
  assert.deepEqual(resp.tracks.map((t) => t.id), ["t1", "t2", "t3", "t4"]);
  assert.equal(resp.undo, null);
  await assert.rejects(() => dispatch(player, {}, { cmd: "queue.undo" }), /nothing to undo/);
});

test("music-player-ctl spells the new commands like the others", () => {
  assert.deepEqual(parseCtlArgs(["queue.undo"]), { cmd: "queue.undo" });
  assert.deepEqual(parseCtlArgs(["queue.clear_upcoming"]), { cmd: "queue.clear_upcoming" });
});
