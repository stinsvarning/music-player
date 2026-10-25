import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { setTimeout as delay } from "node:timers/promises";
import { StatusHub } from "../src/events.js";
import { Player } from "../src/player.js";
import { listen } from "../src/server.js";

function fakeSock() {
  const sock = new EventEmitter();
  sock.lines = [];
  sock.destroyed = false;
  sock.writable = true;
  sock.write = (line) => sock.lines.push(JSON.parse(line));
  return sock;
}

function fakePlayer(initial = {}) {
  const listeners = new Set();
  const player = {
    st: { state: "paused", position: 10, track: { id: "a" }, queue_sig: "0:a", volume: 50, ...initial },
    calls: 0,
    onChange(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    change(patch) {
      Object.assign(this.st, patch);
      for (const fn of listeners) fn("test");
    },
    async status() {
      this.calls += 1;
      return { ...this.st };
    },
  };
  return player;
}

test("hub pushes a change once, coalesced, and skips identical snapshots", async () => {
  const player = fakePlayer();
  const hub = new StatusHub(player, { debounceMs: 5, heartbeatMs: 10_000 });
  const sock = fakeSock();
  const first = await hub.add(sock);
  assert.equal(first.track.id, "a");
  player.change({ volume: 60 });
  player.change({ volume: 61 });
  await delay(30);
  assert.equal(sock.lines.length, 1);
  assert.equal(sock.lines[0].event, "status");
  assert.equal(sock.lines[0].ok, true);
  assert.equal(sock.lines[0].volume, 61);
  player.change({});
  await delay(30);
  assert.equal(sock.lines.length, 1, "nothing changed, nothing sent");
  hub.close();
});

test("hub reports a seek but not ordinary position drift", async () => {
  const player = fakePlayer({ state: "paused", position: 10 });
  const hub = new StatusHub(player, { debounceMs: 5, heartbeatMs: 10_000 });
  const sock = fakeSock();
  await hub.add(sock);
  player.change({ position: 10.4 });
  await delay(30);
  assert.equal(sock.lines.length, 0);
  player.change({ position: 90 });
  await delay(30);
  assert.equal(sock.lines.length, 1);
  assert.equal(sock.lines[0].position, 90);
  hub.close();
});

test("hub heartbeats only while playing and stops when clients leave", async () => {
  const player = fakePlayer({ state: "playing" });
  const hub = new StatusHub(player, { debounceMs: 5, heartbeatMs: 20 });
  const sock = fakeSock();
  await hub.add(sock);
  await delay(75);
  assert.ok(sock.lines.length >= 2, `heartbeat while playing (${sock.lines.length})`);
  player.change({ state: "paused" });
  await delay(30);
  const n = sock.lines.length;
  await delay(80);
  assert.equal(sock.lines.length, n, "no heartbeat while paused");
  sock.emit("close");
  assert.equal(hub.size, 0);
  const calls = player.calls;
  player.change({ volume: 1 });
  await delay(30);
  assert.equal(player.calls, calls, "no status work without subscribers");
  hub.close();
});

test("player notifies on queue edits, transport and mpv events", async () => {
  const listeners = new Set();
  const mpv = {
    onEvent: (fn) => listeners.add(fn),
    async load() {},
    async pause() {},
    async get() {
      return null;
    },
    async seekAbsolute() {},
  };
  const player = new Player({ mpv, youtube: { streamUrl: async (id) => `mem://${id}` } });
  const reasons = [];
  player.onChange((r) => reasons.push(r));
  player.replaceQueue([{ id: "a" }, { id: "b" }], 0);
  player.queueTrack({ id: "c" });
  await player.playIndex(1);
  await player.seek(5);
  for (const fn of listeners) fn({ event: "property-change", name: "pause", data: true });
  assert.ok(reasons.length >= 5, reasons.join(","));
  assert.ok(reasons.includes("mpv:property-change:pause"));
});

test("subscribe turns a connection into a status stream", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "music-sub-"));
  const socketPath = path.join(dir, "engine.sock");
  const player = fakePlayer();
  const hub = new StatusHub(player, { debounceMs: 5, heartbeatMs: 10_000 });
  const server = await listen(socketPath, async () => ({ ok: true, plain: true }), { onSubscribe: (sock) => hub.add(sock) });
  const client = net.createConnection(socketPath);
  await new Promise((r) => client.once("connect", r));
  const lines = [];
  let buf = "";
  client.on("data", (chunk) => {
    buf += chunk.toString();
    while (buf.includes("\n")) {
      const i = buf.indexOf("\n");
      lines.push(JSON.parse(buf.slice(0, i)));
      buf = buf.slice(i + 1);
    }
  });
  client.write('{"cmd":"subscribe"}\n');
  await delay(40);
  assert.equal(lines[0].ok, true);
  assert.equal(lines[0].subscribed, true);
  assert.equal(lines[0].track.id, "a");
  player.change({ track: { id: "b" }, queue_sig: "0:b" });
  await delay(40);
  assert.equal(lines.at(-1).event, "status");
  assert.equal(lines.at(-1).track.id, "b");
  client.write('{"cmd":"status"}\n');
  await delay(40);
  assert.equal(lines.at(-1).plain, true, "ordinary commands still work on the same socket");
  client.end();
  await delay(20);
  assert.equal(hub.size, 0);
  hub.close();
  await new Promise((r) => server.close(r));
});

test("subscribe without a hub fails cleanly", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "music-sub-"));
  const socketPath = path.join(dir, "engine.sock");
  const server = await listen(socketPath, async () => ({ ok: true }));
  const client = net.createConnection(socketPath);
  await new Promise((r) => client.once("connect", r));
  const line = await new Promise((resolve) => {
    client.once("data", (chunk) => resolve(JSON.parse(chunk.toString().split("\n")[0])));
    client.write('{"cmd":"subscribe"}\n');
  });
  assert.equal(line.ok, false);
  client.end();
  await new Promise((r) => server.close(r));
});
