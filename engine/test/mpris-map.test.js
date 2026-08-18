import assert from "node:assert/strict";
import { test } from "node:test";
import { loopStatus, metadataFromStatus, mprisVolume, playbackStatus } from "../src/mpris-map.js";

test("playback and loop map to MPRIS strings", () => {
  assert.equal(playbackStatus("playing"), "Playing");
  assert.equal(playbackStatus("paused"), "Paused");
  assert.equal(playbackStatus("stopped"), "Stopped");
  assert.equal(loopStatus("off"), "None");
  assert.equal(loopStatus("one"), "Track");
  assert.equal(loopStatus("all"), "Playlist");
});

test("volume is 0-1", () => {
  assert.equal(mprisVolume(0), 0);
  assert.equal(mprisVolume(50), 0.5);
  assert.equal(mprisVolume(100), 1);
});

test("metadata includes title artist art and length", () => {
  const meta = metadataFromStatus({
    duration: 125,
    track: { id: "abc", title: "Hello", artist: "World", album: "LP", path: "https://x" },
  });
  assert.equal(meta["xesam:title"], "Hello");
  assert.deepEqual(meta["xesam:artist"], ["World"]);
  assert.equal(meta["mpris:length"], 125_000_000);
  assert.match(meta["mpris:artUrl"], /abc/);
});
