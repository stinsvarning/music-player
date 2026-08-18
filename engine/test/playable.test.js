import assert from "node:assert/strict";
import { test } from "node:test";
import {
  infoLooksUnplayable,
  isUnplayableError,
  itemLooksUnplayable,
  unplayableError,
} from "../src/playable.js";
import { extractSongs } from "../src/mix.js";
import { Player } from "../src/player.js";

function track(id, extra = {}) {
  return { id, title: id, artist: "a", duration_secs: extra.duration_secs ?? 10, playable: extra.playable };
}

function fakeMpv() {
  return {
    loads: [],
    async load(url) {
      this.loads.push(url);
    },
    async pause() {},
    async get() {
      return null;
    },
    async setVolume() {},
    async setAf() {},
    seeks: [],
    async seekAbsolute(seconds) {
      this.seeks.push(seconds);
    },
  };
}

test("itemLooksUnplayable reads playlist restriction flags", () => {
  assert.equal(itemLooksUnplayable({ id: "ok" }), false);
  assert.equal(itemLooksUnplayable({ id: "a", unplayable: true }), true);
  assert.equal(itemLooksUnplayable({ id: "b", playable: false }), true);
  assert.equal(itemLooksUnplayable({ id: "c", playability_status: { status: "UNPLAYABLE", reason: "error 150" } }), true);
});

test("infoLooksUnplayable does not retry embed blocks", () => {
  assert.equal(infoLooksUnplayable({ playability_status: { status: "OK" } }), "");
  assert.match(infoLooksUnplayable({ playability_status: { status: "UNPLAYABLE", reason: "restricted" } }), /restricted|unavailable/);
  assert.equal(infoLooksUnplayable({ playability_status: { playable_in_embed: false } }), "youtube-only");
});

test("extractSongs marks restricted playlist rows", () => {
  const songs = extractSongs([
    { id: "aaa", item_type: "song", title: "One" },
    { id: "bbb", item_type: "song", title: "Two", playable: false },
  ]);
  assert.equal(songs[0].playable, true);
  assert.equal(songs[1].playable, false);
});

test("isUnplayableError matches the typed error", () => {
  assert.equal(isUnplayableError(unplayableError("150")), true);
  assert.equal(isUnplayableError(new Error("http 403")), false);
});

test("next skips an unplayable track and plays the following one", async () => {
  const mpv = fakeMpv();
  const player = new Player({
    mpv,
    youtube: {
      streamUrl: async (id) => {
        if (id === "blocked") {
          throw unplayableError("150");
        }
        return `mem://${id}`;
      },
    },
  });
  player.replaceQueue([track("a"), track("blocked"), track("c")], 0);
  player.state = "playing";
  await player.next();
  assert.equal(player.index, 2);
  assert.equal(player.queue[1].playable, false);
  assert.ok(mpv.loads.includes("mem://c"));
});
