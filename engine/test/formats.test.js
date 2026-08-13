import assert from "node:assert/strict";
import { test } from "node:test";
import { pickAudioFormat } from "../src/formats.js";

test("prefers itag 140 over higher-bitrate opus", () => {
  const picked = pickAudioFormat([
    { itag: 251, has_audio: true, has_video: false, bitrate: 160000 },
    { itag: 140, has_audio: true, has_video: false, bitrate: 128000 },
    { itag: 18, has_audio: true, has_video: true, bitrate: 500000 },
  ]);
  assert.equal(picked.itag, 140);
});

test("falls back to best audio-only bitrate", () => {
  const picked = pickAudioFormat([
    { itag: 251, has_audio: true, has_video: false, bitrate: 160000 },
    { itag: 250, has_audio: true, has_video: false, bitrate: 70000 },
  ]);
  assert.equal(picked.itag, 251);
});

test("returns null when empty", () => {
  assert.equal(pickAudioFormat([]), null);
});
