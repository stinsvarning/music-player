import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";
import { COMMANDS, commandCatalog, commandRisk } from "../src/commands.js";
import { dispatch } from "../src/server.js";
import { attachId, fail, ok } from "../src/protocol.js";

function dispatchCases() {
  const src = fs.readFileSync(new URL("../src/server.js", import.meta.url), "utf8");
  return [...src.matchAll(/case "([^"]+)":/g)].map((m) => m[1]);
}

test("catalog covers every dispatch command plus auth verbs", () => {
  const names = new Set(COMMANDS.map((c) => c.cmd));
  for (const cmd of dispatchCases()) {
    assert.ok(names.has(cmd), `missing catalog entry for ${cmd}`);
  }
  for (const cmd of ["auth.status", "auth.refresh", "auth.logout", "help", "commands"]) {
    assert.ok(names.has(cmd), `missing catalog entry for ${cmd}`);
  }
});

test("shutdown and auth.refresh are dangerous", () => {
  const byName = Object.fromEntries(COMMANDS.map((c) => [c.cmd, c]));
  assert.equal(byName.shutdown.risk, "dangerous");
  assert.equal(byName["auth.refresh"].risk, "dangerous");
  assert.equal(byName.search.risk, "read");
  assert.equal(byName.status.risk, "read");
  assert.equal(commandRisk("shutdown"), "dangerous");
  assert.equal(commandRisk("status"), "read");
  assert.equal(commandRisk("nope"), null);
  assert.equal(byName["playlist.tracks"].risk, "read");
  assert.ok(!byName["playlist.tracks"].args.some((a) => a.name === "load"));
  assert.equal(byName["playlist.play"].risk, "write");
});

test("playlist.tracks browses even when load is set", async () => {
  const calls = [];
  const player = {
    replaceQueue(...args) {
      calls.push(["replace", ...args]);
    },
    async playIndex(...args) {
      calls.push(["play", ...args]);
    },
  };
  const youtube = {
    playlistTracksPage: async (id) => ({ tracks: [{ id: "a", title: id }], done: true }),
    playlistTracks: async () => {
      calls.push(["full"]);
      return [{ id: "a" }, { id: "b" }];
    },
  };
  const resp = await dispatch(player, youtube, { cmd: "playlist.tracks", id: "PL1", load: true });
  assert.equal(resp.ok, true);
  assert.equal(resp.tracks[0].id, "a");
  assert.deepEqual(calls, []);
});

test("track.play does not start a mix when Play similar is on", async () => {
  const player = {
    automix: true,
    queue: [{ id: "old" }],
    index: 0,
    async startMix() {
      throw new Error("track.play must not start a mix");
    },
    async playTrack(track, opts) {
      player.played = { track, opts };
    },
  };
  const resp = await dispatch(player, {}, { cmd: "track.play", track: { id: "new" } });
  assert.equal(resp.ok, true);
  assert.equal(player.played.track.id, "new");
  assert.deepEqual(player.played.opts, { replaceQueue: true });
});

test("help returns the catalog without needing a player", async () => {
  const resp = await dispatch({}, {}, { cmd: "help" });
  assert.equal(resp.ok, true);
  assert.ok(resp.commands.some((c) => c.cmd === "search"));
  assert.equal(
    resp.commands.find((c) => c.cmd === "shutdown").risk,
    "dangerous",
  );
});

test("attachId copies a request id onto the reply", () => {
  assert.deepEqual(attachId({ cmd: "status", id: 7 }, ok({ state: "playing" })), {
    ok: true,
    state: "playing",
    id: 7,
  });
  assert.deepEqual(attachId({ cmd: "status" }, fail("nope")), { ok: false, error: "nope" });
});

test("commandCatalog is a copy", () => {
  const a = commandCatalog();
  a.pop();
  assert.equal(commandCatalog().length, COMMANDS.length);
});
