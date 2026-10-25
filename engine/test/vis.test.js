import assert from "node:assert/strict";
import { test } from "node:test";
import { VIS_MODES, visModeName } from "../src/eq.js";
import { Player } from "../src/player.js";
import { serializeSession } from "../src/session.js";
import { COMMANDS } from "../src/commands.js";

function fakeMpv() {
  return {
    afs: [],
    onEvent() {},
    async get() {
      return null;
    },
    async setVolume() {},
    async setAf(value) {
      this.afs.push(value);
    },
  };
}

function makePlayer() {
  const mpv = fakeMpv();
  const saved = [];
  const player = new Player({ mpv, youtube: {}, persist: { save: (s) => saved.push(s) } });
  return { player, mpv, saved };
}

const taps = (af) => af.includes("astats");

test("visualizer names: four looks, old aliases, junk rejected", () => {
  assert.deepEqual(VIS_MODES, ["bricks", "wave", "waterfall", "off"]);
  assert.equal(visModeName(" OFF "), "off");
  assert.equal(visModeName("orbit"), "waterfall");
  assert.equal(visModeName("spiral"), null);
  assert.equal(visModeName(undefined), null);
});

test("off drops the spectrum taps from mpv and stops band sampling", async () => {
  const { player, mpv } = makePlayer();
  let reads = 0;
  player.readBands = () => {
    reads += 1;
    return Array(10).fill(0.5);
  };
  player.state = "playing";
  await player.applyEq();
  assert.ok(taps(mpv.afs.at(-1)));
  assert.deepEqual(await player.bands(), Array(10).fill(0.5));
  await player.setVis("off");
  assert.equal(player.analysing, false);
  assert.equal(player._bandsTimer, null);
  assert.ok(!taps(mpv.afs.at(-1)));
  const before = reads;
  assert.deepEqual(await player.bands(), Array(10).fill(0));
  assert.equal(reads, before); // no file reads while off
  assert.equal(player._bandsTimer, null);
  const status = await player.status();
  assert.equal(status.vis_mode, "off");
  assert.equal(status.vis_on, false);
});

test("turning a look back on restores the taps once; switching looks leaves mpv alone", async () => {
  const { player, mpv } = makePlayer();
  await player.setVis("wave");
  assert.equal(mpv.afs.length, 0); // already analysing: no filter change
  await player.setVis("off");
  await player.setVis("off");
  assert.equal(mpv.afs.length, 1);
  await player.setVis("bricks");
  assert.equal(mpv.afs.length, 2);
  assert.ok(taps(mpv.afs.at(-1)));
  player.readBands = () => Array(10).fill(0.25);
  player.state = "playing";
  assert.deepEqual(await player.bands(), Array(10).fill(0.25));
  player.stopBands();
});

test("the chosen look is saved in the session and restored before mpv starts", async () => {
  const { player, saved } = makePlayer();
  await player.setVis("off");
  assert.equal(saved.at(-1).vis_mode, "off");
  assert.equal(serializeSession(saved.at(-1)).vis_mode, "off");
  const next = makePlayer();
  next.player.restoreSession(serializeSession(saved.at(-1)));
  assert.equal(next.player.visMode, "off");
  await next.player.applyEq();
  assert.ok(!taps(next.mpv.afs.at(-1))); // a restart with off saved never starts the taps
});

test("an unsaved sync applies the look without remembering it", async () => {
  const { player, saved } = makePlayer();
  await player.setVis("off", { save: false });
  assert.equal(player.analysing, false);
  assert.equal(player.visSaved, null);
  assert.equal(saved.length, 0);
  await assert.rejects(player.setVis("spiral"));
});

test("sessions without a saved look keep the visualizer on", () => {
  const { player } = makePlayer();
  player.restoreSession(serializeSession({ tracks: [] }));
  assert.equal(player.visSaved, null);
  assert.equal(player.analysing, true);
  assert.equal(serializeSession({ vis_mode: "orbit" }).vis_mode, "waterfall");
  assert.equal(serializeSession({ vis_mode: "nope" }).vis_mode, null);
});

test("vis is an engine command", () => {
  const row = COMMANDS.find((r) => r.cmd === "vis");
  assert.equal(row.risk, "write");
  assert.deepEqual(row.args.map((a) => a.name), ["mode", "save"]);
});
