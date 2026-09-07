import assert from "node:assert/strict";
import { test } from "node:test";
import { pickAudioFormat } from "../src/formats.js";

test("prefers AUDIO_QUALITY_HIGH even when a medium stream has higher bitrate", () => {
  const picked = pickAudioFormat([
    { itag: 774, has_audio: true, has_video: false, bitrate: 160000, audio_quality: "AUDIO_QUALITY_HIGH" },
    { itag: 251, has_audio: true, has_video: false, bitrate: 320000, audio_quality: "AUDIO_QUALITY_MEDIUM" },
    { itag: 140, has_audio: true, has_video: false, bitrate: 128000, audio_quality: "AUDIO_QUALITY_LOW" },
  ]);
  assert.equal(picked.itag, 774);
});

test("prefers high AAC over normal AAC and opus", () => {
  const picked = pickAudioFormat([
    { itag: 141, has_audio: true, has_video: false, bitrate: 256000, audio_quality: "AUDIO_QUALITY_HIGH" },
    { itag: 251, has_audio: true, has_video: false, bitrate: 160000, audio_quality: "AUDIO_QUALITY_MEDIUM" },
    { itag: 140, has_audio: true, has_video: false, bitrate: 128000, audio_quality: "AUDIO_QUALITY_MEDIUM" },
    { itag: 18, has_audio: true, has_video: true, bitrate: 500000 },
  ]);
  assert.equal(picked.itag, 141);
});

test("prefers higher-bitrate audio-only over itag 140", () => {
  const picked = pickAudioFormat([
    { itag: 251, has_audio: true, has_video: false, bitrate: 160000 },
    { itag: 140, has_audio: true, has_video: false, bitrate: 128000 },
    { itag: 18, has_audio: true, has_video: true, bitrate: 500000 },
  ]);
  assert.equal(picked.itag, 251);
});

test("uses average_bitrate when bitrate is missing", () => {
  const picked = pickAudioFormat([
    { itag: 141, has_audio: true, has_video: false, average_bitrate: 256000 },
    { itag: 140, has_audio: true, has_video: false, bitrate: 128000 },
  ]);
  assert.equal(picked.itag, 141);
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
