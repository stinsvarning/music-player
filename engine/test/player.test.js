import assert from "node:assert/strict";
import { test } from "node:test";
import { Player } from "../src/player.js";

function track(id, extra = {}) {
  return { id, title: id, artist: "a", duration_secs: extra.duration_secs ?? 10 };
}

function fakeMpv() {
  const listeners = new Set();
  const loads = [];
  return {
    loads,
    onEvent(fn) {
      listeners.add(fn);
    },
    emit(ev) {
      for (const fn of listeners) {
        fn(ev);
      }
    },
    async load(url) {
      loads.push(url);
    },
    async pause() {},
    async get() {
      return null;
    },
    async setVolume(value) {
      this.volume = value;
    },
    async setAf() {},
    seeks: [],
    async seekAbsolute(seconds) {
      this.seeks.push(seconds);
    },
  };
}

function fakeYt(extra = {}) {
  return {
    streamUrl: async (id) => `mem://${id}`,
    mix: async (id) => ({
      tracks: [track(id), track(`${id}-2`), track(`${id}-3`)],
      title: "Mix",
    }),
    similar: extra.similar || (async (id, { exclude = [] } = {}) => {
      const skip = new Set(exclude);
      return [track("x1"), track("x2")].filter((t) => !skip.has(t.id));
    }),
    ...extra,
  };
}

function makePlayer() {
  const mpv = fakeMpv();
  const player = new Player({ mpv, youtube: fakeYt() });
  return { player, mpv };
}

test("enabling shuffle keeps the current track and permutes the rest", () => {
  const { player } = makePlayer();
  player.replaceQueue([track("a"), track("b"), track("c"), track("d")], 1);
  const orig = Math.random;
  Math.random = () => 0;
  try {
    player.setShuffle("on");
  } finally {
    Math.random = orig;
  }
  assert.equal(player.shuffle, true);
  assert.equal(player.queue[player.index].id, "b");
  assert.deepEqual(new Set(player.queue.map((t) => t.id)), new Set(["a", "b", "c", "d"]));
  assert.notDeepEqual(
    player.queue.slice(player.index + 1).map((t) => t.id),
    ["c", "d"],
  );
});

test("playNext inserts immediately after the current track", () => {
  const { player } = makePlayer();
  player.replaceQueue([track("a"), track("b")], 0);
  player.playNext(track("c"));
  assert.deepEqual(
    player.queue.map((t) => t.id),
    ["a", "c", "b"],
  );
});

test("playTrack replaceQueue leaves only the chosen track", async () => {
  const { player } = makePlayer();
  player.setAutomix("off");
  player.replaceQueue([track("a"), track("b"), track("c")], 0);
  await player.playTrack(track("z"), { replaceQueue: true });
  assert.deepEqual(
    player.queue.map((t) => t.id),
    ["z"],
  );
  assert.equal(player.index, 0);
});

test("sleep timer stops playback when it is due", async () => {
  const { player } = makePlayer();
  player.replaceQueue([track("a")], 0);
  player.state = "playing";
  player.setSleep(15);
  assert.ok((await player.status()).sleep_remaining > 0);
  player.sleepUntil = Date.now() - 10;
  const st = await player.status();
  assert.equal(player.state, "stopped");
  assert.equal(st.sleep_remaining, 0);
});

test("restoreSession keeps a future sleep deadline", () => {
  const { player } = makePlayer();
  const until = Date.now() + 20 * 60 * 1000;
  player.restoreSession({
    tracks: [track("a")],
    index: 0,
    sleep_until: until,
    sleep_minutes: 20,
  });
  assert.equal(player.sleepMinutes, 20);
  assert.ok(player.sleepUntil > Date.now());
  assert.ok(player.sleepRemaining() > 0);
});

test("restoreSession ignores a sleep deadline that already passed", () => {
  const { player } = makePlayer();
  player.restoreSession({
    tracks: [track("a")],
    index: 0,
    sleep_until: Date.now() - 50,
    sleep_minutes: 20,
  });
  assert.equal(player.sleepUntil, 0);
  assert.equal(player.sleepMinutes, 0);
});

test("setSleep notifies persist", () => {
  const snaps = [];
  const { player } = makePlayer();
  player.persist = (snap) => snaps.push(snap);
  player.setSleep(15);
  assert.equal(snaps.at(-1).sleep_minutes, 15);
  assert.ok(snaps.at(-1).sleep_until > Date.now());
  player.setSleep(0);
  assert.equal(snaps.at(-1).sleep_until, 0);
});

test("setSleep 0 clears the timer", () => {
  const { player } = makePlayer();
  player.setSleep(20);
  player.setSleep(0);
  assert.equal(player.sleepUntil, 0);
  assert.equal(player.sleepMinutes, 0);
});

test("queueTrack appends to the end", () => {
  const { player } = makePlayer();
  player.replaceQueue([track("a")], 0);
  player.queueTrack(track("b"));
  assert.deepEqual(
    player.queue.map((t) => t.id),
    ["a", "b"],
  );
});

test("move keeps the playing identity when the current row is dragged", () => {
  const { player } = makePlayer();
  player.replaceQueue([track("a"), track("b"), track("c")], 1);
  player.move(1, 2);
  assert.deepEqual(
    player.queue.map((t) => t.id),
    ["a", "c", "b"],
  );
  assert.equal(player.index, 2);
  assert.equal(player.queue[player.index].id, "b");
});

test("move into the current slot shifts the playing index", () => {
  const { player } = makePlayer();
  player.replaceQueue([track("a"), track("b"), track("c")], 1);
  player.move(2, 0);
  assert.deepEqual(
    player.queue.map((t) => t.id),
    ["c", "a", "b"],
  );
  assert.equal(player.queue[player.index].id, "b");
});

test("repeat all wraps to the start", async () => {
  const { player } = makePlayer();
  player.replaceQueue([track("a"), track("b")], 1);
  player.setRepeat("all");
  await player.next();
  assert.equal(player.index, 0);
  assert.equal(player.state, "playing");
});

test("play similar is off until the user turns it on", () => {
  const { player } = makePlayer();
  assert.equal(player.automix, false);
});

test("restoreSession reapplies queue and flags without starting playback", () => {
  const { player, mpv } = makePlayer();
  const ok = player.restoreSession({
    tracks: [track("a"), track("b"), track("c")],
    index: 2,
    shuffle: true,
    repeat: "all",
    automix: true,
  });
  assert.equal(ok, true);
  assert.deepEqual(
    player.queue.map((t) => t.id),
    ["a", "b", "c"],
  );
  assert.equal(player.index, 2);
  assert.equal(player.shuffle, true);
  assert.equal(player.repeat, "all");
  assert.equal(player.automix, true);
  assert.equal(player.state, "stopped");
  assert.equal(mpv.loads.length, 0);
  assert.equal(player.volumeLevel, 70);
  assert.equal(player.eqPreset, "Flat");
  assert.equal(player.position, 0);
});

test("restoreSession keeps the playhead and play seeks there", async () => {
  const { player, mpv } = makePlayer();
  player.restoreSession({
    tracks: [track("a", { duration_secs: 200 })],
    index: 0,
    position: 42,
  });
  assert.equal(player.position, 42);
  assert.equal(player.state, "stopped");
  const st = await player.status();
  assert.equal(st.position, 42);
  assert.equal(mpv.loads.length, 0);
  await player.play();
  assert.deepEqual(mpv.seeks, [42]);
  assert.equal(player.state, "playing");
});

test("next after a restored playhead starts the following track at zero", async () => {
  const { player } = makePlayer();
  player.restoreSession({
    tracks: [track("a"), track("b")],
    index: 0,
    position: 30,
  });
  await player.next();
  assert.equal(player.index, 1);
  assert.equal(player.position, 0);
});

test("load retries once after dropping a cached url", async () => {
  const { player, mpv } = makePlayer();
  player.cache.set("a", "https://stale.example/a?expire=9999999999");
  let fetches = 0;
  player.youtube.streamUrl = async (id) => {
    fetches += 1;
    return `https://fresh.example/${id}`;
  };
  mpv.load = async (url) => {
    mpv.loads.push(url);
    if (String(url).includes("stale")) {
      throw new Error("http 403");
    }
  };
  player.replaceQueue([track("a")], 0);
  await player.playIndex(0);
  assert.deepEqual(mpv.loads, ["https://stale.example/a?expire=9999999999", "https://fresh.example/a"]);
  assert.equal(fetches, 1);
  assert.equal(player.cache.get("a"), "https://fresh.example/a");
});

test("status follows mpv when the engine state was left stopped", async () => {
  const { player, mpv } = makePlayer();
  player.replaceQueue([track("a")], 0);
  player.state = "stopped";
  mpv.get = async (prop) => {
    if (prop === "pause") {
      return false;
    }
    if (prop === "idle-active") {
      return false;
    }
    if (prop === "time-pos") {
      return 12;
    }
    if (prop === "duration") {
      return 200;
    }
    return null;
  };
  const st = await player.status();
  assert.equal(st.state, "playing");
  assert.equal(st.position, 12);
});

test("status stays stopped when mpv is idle even if pause is false", async () => {
  const { player, mpv } = makePlayer();
  player.replaceQueue([track("a")], 0);
  player.state = "stopped";
  mpv.get = async (prop) => {
    if (prop === "pause") {
      return false;
    }
    if (prop === "idle-active") {
      return true;
    }
    return null;
  };
  const st = await player.status();
  assert.equal(st.state, "stopped");
});

test("status reports paused when mpv is idle after playing", async () => {
  const { player, mpv } = makePlayer();
  player.replaceQueue([track("a")], 0);
  player.state = "playing";
  mpv.get = async (prop) => {
    if (prop === "pause") {
      return false;
    }
    if (prop === "idle-active") {
      return true;
    }
    if (prop === "time-pos") {
      return 12;
    }
    return null;
  };
  const st = await player.status();
  assert.equal(st.state, "paused");
});

test("play loads again when state is playing but mpv is idle", async () => {
  const { player, mpv } = makePlayer();
  player.replaceQueue([track("a")], 0);
  player.state = "playing";
  mpv.get = async (prop) => (prop === "idle-active" ? true : null);
  await player.play();
  assert.ok(mpv.loads.includes("mem://a"));
  assert.equal(player.state, "playing");
});

test("play retries resume seek until mpv accepts it", async () => {
  const { player, mpv } = makePlayer();
  player._sleep = async () => {};
  player.restoreSession({
    tracks: [track("a", { duration_secs: 200 })],
    index: 0,
    position: 42,
  });
  let tries = 0;
  mpv.seekAbsolute = async (seconds) => {
    tries += 1;
    if (tries < 3) {
      throw new Error("not seekable");
    }
    mpv.seeks.push(seconds);
  };
  await player.play();
  assert.equal(tries, 3);
  assert.deepEqual(mpv.seeks, [42]);
});

test("play still starts if the resume seek fails", async () => {
  const { player, mpv } = makePlayer();
  player._sleep = async () => {};
  player.replaceQueue([track("a", { duration_secs: 200 })], 0);
  player.position = 40;
  mpv.seekAbsolute = async () => {
    throw new Error("seek failed");
  };
  await player.play();
  assert.equal(player.state, "playing");
  assert.ok(mpv.loads.includes("mem://a"));
});

test("load failure of a freshly resolved url is not retried", async () => {
  const { player, mpv } = makePlayer();
  let fetches = 0;
  player.youtube.streamUrl = async (id) => {
    fetches += 1;
    return `https://fresh.example/${id}`;
  };
  mpv.load = async () => {
    throw new Error("http 403");
  };
  player.replaceQueue([track("a")], 0);
  await assert.rejects(() => player.playIndex(0), /403/);
  assert.equal(fetches, 1);
});

test("seek updates the persisted playhead", async () => {
  const snaps = [];
  const { player } = makePlayer();
  player.persist = (snap) => snaps.push(snap);
  player.replaceQueue([track("a")], 0);
  await player.seek(18);
  assert.equal(player.position, 18);
  assert.equal(snaps.at(-1).position, 18);
});

test("restoreSession reapplies volume and EQ without starting playback", async () => {
  const { player, mpv } = makePlayer();
  const ok = player.restoreSession({
    tracks: [track("a")],
    index: 0,
    volume: 35,
    eq_preset: "Warm",
    eq_bands: [2, 2, 1, 0, 0, 0, 0, 1, 1, 1],
  });
  assert.equal(ok, true);
  assert.equal(player.volumeLevel, 35);
  assert.equal(player.eqPreset, "Warm");
  assert.deepEqual(player.eqBands, [2, 2, 1, 0, 0, 0, 0, 1, 1, 1]);
  await player.applyVolume();
  await player.applyEq();
  assert.equal(mpv.volume, 35);
  assert.equal(mpv.loads.length, 0);
});

test("volume and EQ changes notify persist", async () => {
  const snaps = [];
  const { player } = makePlayer();
  player.persist = (snap) => snaps.push(snap);
  await player.volume(22);
  await player.setEqPreset("Night");
  const last = snaps.at(-1);
  assert.equal(last.volume, 22);
  assert.equal(last.eq_preset, "Night");
});

test("queue and flag changes notify persist", () => {
  const snaps = [];
  const { player } = makePlayer();
  player.persist = (snap) => snaps.push(snap);
  player.queueTrack(track("a"));
  player.setAutomix("on");
  player.setRepeat("one");
  player.setShuffle("off");
  assert.ok(snaps.length >= 3);
  const last = snaps.at(-1);
  assert.deepEqual(
    last.tracks.map((t) => t.id),
    ["a"],
  );
  assert.equal(last.automix, true);
  assert.equal(last.repeat, "one");
});

test("restoreSession does not notify persist", () => {
  let called = 0;
  const { player } = makePlayer();
  player.persist = () => {
    called += 1;
  };
  player.restoreSession({ tracks: [track("a")], index: 0, automix: true });
  assert.equal(called, 0);
  assert.equal(player.automix, true);
});

test("repeat off stops after the last track when automix is off", async () => {
  const { player } = makePlayer();
  player.replaceQueue([track("a"), track("b")], 1);
  player.setRepeat("off");
  player.setAutomix("off");
  await player.next();
  assert.equal(player.state, "stopped");
});

test("play after the last track starts from the beginning", async () => {
  const { player, mpv } = makePlayer();
  player.replaceQueue([track("a", { duration_secs: 200 }), track("b", { duration_secs: 180 })], 1);
  player.position = 179;
  player.state = "playing";
  player.setRepeat("off");
  player.setAutomix("off");
  await player.next();
  assert.equal(player.state, "stopped");
  assert.equal(player.position, 0);
  await player.play();
  assert.equal(player.state, "playing");
  assert.ok(mpv.loads.includes("mem://b"));
  assert.equal(mpv.seeks.includes(179), false);
});

test("startMix replaces the queue with radio tracks", async () => {
  const { player } = makePlayer();
  player.replaceQueue([track("old")], 0);
  await player.startMix(track("seed"));
  assert.deepEqual(
    player.queue.map((t) => t.id),
    ["seed", "seed-2", "seed-3"],
  );
  assert.equal(player.index, 0);
  assert.equal(player.automix, true);
  assert.equal(player.state, "playing");
});

test("automix appends similar tracks when the queue ends", async () => {
  const { player } = makePlayer();
  player.replaceQueue([track("a"), track("b")], 1);
  player.setAutomix("on");
  player.setRepeat("off");
  await player.next();
  assert.equal(player.state, "playing");
  assert.ok(player.queue.length > 2);
  assert.equal(player.queue[player.index].id, "x1");
});

test("repeat all does not fetch automix", async () => {
  let called = 0;
  const { player } = makePlayer();
  player.youtube.similar = async () => {
    called += 1;
    return [track("nope")];
  };
  player.replaceQueue([track("a"), track("b")], 1);
  player.setRepeat("all");
  player.setAutomix("on");
  await player.next();
  assert.equal(player.index, 0);
  assert.equal(called, 0);
});

test("repeat one reloads the same index", async () => {
  const { player, mpv } = makePlayer();
  player.replaceQueue([track("a"), track("b")], 0);
  player.setRepeat("one");
  await player.next();
  assert.equal(player.index, 0);
  assert.ok(mpv.loads.includes("mem://a"));
});

test("end-file eof advances to the next track", async () => {
  const { player, mpv } = makePlayer();
  player.replaceQueue([track("a"), track("b")], 0);
  player.state = "playing";
  mpv.emit({ event: "end-file", reason: "eof" });
  await new Promise((r) => setTimeout(r, 20));
  assert.equal(player.index, 1);
  assert.equal(player.queue[player.index].id, "b");
});

test("bands while stopped returns zeros without reading files", async () => {
  let reads = 0;
  const { player } = makePlayer();
  player.readBands = () => {
    reads += 1;
    return Array(10).fill(0.4);
  };
  player.state = "stopped";
  const bands = await player.bands();
  assert.deepEqual(bands, Array(10).fill(0));
  assert.equal(reads, 0);
  player.stopBands();
});

test("bands while playing samples once then returns the in-memory cache", async () => {
  let reads = 0;
  const sample = [0.9, 0.1, 0, 0, 0, 0, 0, 0, 0, 0];
  const { player } = makePlayer();
  player.readBands = () => {
    reads += 1;
    return [...sample];
  };
  player.state = "playing";
  const first = await player.bands();
  const second = await player.bands();
  assert.deepEqual(first, sample);
  assert.deepEqual(second, sample);
  assert.equal(reads, 1);
  player.stopBands();
});

test("end-file from a replace does not skip a track", async () => {
  const { player, mpv } = makePlayer();
  player.replaceQueue([track("a"), track("b"), track("c")], 0);
  await player.playIndex(0);
  const afterPlay = player.index;
  mpv.emit({ event: "end-file", reason: "stop" });
  await new Promise((r) => setTimeout(r, 20));
  assert.equal(player.index, afterPlay);
});
