import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { createSessionStore, parseSession, readSession, serializeSession, writeSession } from "../src/session.js";

function track(id, extra = {}) {
  return { id, title: extra.title || id, artist: extra.artist || "a", album: extra.album || "", duration_secs: extra.duration_secs ?? 10 };
}

test("serializeSession keeps queue, index, and transport flags", () => {
  const out = serializeSession({
    tracks: [track("a"), track("b", { title: "Bee", artist: "B", duration_secs: 200 })],
    index: 1,
    shuffle: true,
    repeat: "all",
    automix: true,
    volume: 40,
    eq_preset: "Warm",
    eq_bands: [2, 2, 1, 0, 0, 0, 0, 1, 1, 1],
    position: 42.5,
    sleep_until: Date.now() + 15 * 60 * 1000,
    sleep_minutes: 15,
  });
  assert.equal(out.version, 1);
  assert.equal(out.index, 1);
  assert.equal(out.shuffle, true);
  assert.equal(out.repeat, "all");
  assert.equal(out.automix, true);
  assert.equal(out.volume, 40);
  assert.equal(out.position, 42.5);
  assert.equal(out.sleep_minutes, 15);
  assert.ok(out.sleep_until > Date.now());
  assert.equal(out.eq_preset, "Warm");
  assert.deepEqual(out.eq_bands, [2, 2, 1, 0, 0, 0, 0, 1, 1, 1]);
  assert.deepEqual(
    out.tracks.map((t) => t.id),
    ["a", "b"],
  );
  assert.equal(out.tracks[1].title, "Bee");
});

test("serializeSession defaults volume and a flat EQ", () => {
  const out = serializeSession({ tracks: [track("a")], index: 0 });
  assert.equal(out.volume, 70);
  assert.equal(out.eq_preset, "Flat");
  assert.deepEqual(out.eq_bands, [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]);
  assert.equal(out.position, 0);
  assert.equal(out.sleep_until, 0);
  assert.equal(out.sleep_minutes, 0);
});

test("serializeSession drops a sleep deadline that has already passed", () => {
  const out = serializeSession({
    sleep_until: Date.now() - 1000,
    sleep_minutes: 20,
  });
  assert.equal(out.sleep_until, 0);
  assert.equal(out.sleep_minutes, 0);
});

test("serializeSession drops a position at the end of the current track", () => {
  const out = serializeSession({
    tracks: [track("a", { duration_secs: 200 })],
    index: 0,
    position: 199.2,
  });
  assert.equal(out.position, 0);
});

test("serializeSession clamps volume and EQ bands", () => {
  const out = serializeSession({
    volume: 140,
    eq_preset: "Custom",
    eq_bands: [20, -30, 3],
  });
  assert.equal(out.volume, 100);
  assert.equal(out.eq_preset, "Custom");
  assert.deepEqual(out.eq_bands, [12, -12, 3, 0, 0, 0, 0, 0, 0, 0]);
});

test("serializeSession drops id-less tracks and clamps the index", () => {
  const out = serializeSession({
    tracks: [{ title: "nope" }, track("a"), track("b")],
    index: 99,
    repeat: "nope",
  });
  assert.deepEqual(
    out.tracks.map((t) => t.id),
    ["a", "b"],
  );
  assert.equal(out.index, 1);
  assert.equal(out.repeat, "off");
  assert.equal(out.shuffle, false);
  assert.equal(out.automix, false);
});

test("serializeSession with an empty queue uses index -1", () => {
  const out = serializeSession({ tracks: [], index: 3, automix: true });
  assert.equal(out.index, -1);
  assert.equal(out.automix, true);
});

test("parseSession rejects junk", () => {
  assert.equal(parseSession(null), null);
  assert.equal(parseSession("nope"), null);
  assert.equal(parseSession(12), null);
});

test("writeSession and readSession round-trip a session file", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "music-session-"));
  const file = path.join(dir, "session.json");
  writeSession(file, {
    tracks: [track("x"), track("y")],
    index: 0,
    shuffle: false,
    repeat: "one",
    automix: true,
    volume: 55,
    eq_preset: "Night",
    eq_bands: [1, 0, 0, 0, 0, -1, -2, -3, -2, -2],
  });
  const loaded = readSession(file);
  assert.equal(loaded.repeat, "one");
  assert.equal(loaded.automix, true);
  assert.equal(loaded.volume, 55);
  assert.equal(loaded.eq_preset, "Night");
  assert.deepEqual(
    loaded.tracks.map((t) => t.id),
    ["x", "y"],
  );
  const mode = fs.statSync(file).mode & 0o777;
  assert.equal(mode, 0o600);
});

test("session store writes on flush, not on the first save", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "music-session-"));
  const file = path.join(dir, "session.json");
  const store = createSessionStore(file, { delayMs: 30_000 });
  store.save({ tracks: [track("z")], index: 0, automix: true });
  assert.equal(fs.existsSync(file), false);
  store.flush();
  const loaded = readSession(file);
  assert.equal(loaded.automix, true);
  assert.equal(loaded.tracks[0].id, "z");
});

test("session store flush survives a write failure", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "music-session-"));
  const file = path.join(dir, "session.json");
  fs.mkdirSync(file);
  const store = createSessionStore(file, { delayMs: 30_000 });
  store.save({ tracks: [track("a")], index: 0 });
  store.flush();
});

test("readSession returns null for a missing or corrupt file", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "music-session-"));
  assert.equal(readSession(path.join(dir, "missing.json")), null);
  const bad = path.join(dir, "session.json");
  fs.writeFileSync(bad, "{not json");
  assert.equal(readSession(bad), null);
});
