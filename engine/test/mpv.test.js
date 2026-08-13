import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { setTimeout as delay } from "node:timers/promises";
import { Mpv } from "../src/mpv.js";

test("mpv plays a local file and seeks absolutely", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "mpv-test-"));
  const wav = path.join(dir, "tone.wav");
  const sock = path.join(dir, "mpv.sock");
  const made = spawnSync(
    "ffmpeg",
    ["-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=5", "-ar", "44100", wav],
    { encoding: "utf8" },
  );
  assert.equal(made.status, 0, made.stderr);
  const mpv = new Mpv(sock);
  await mpv.start();
  try {
    await mpv.load(wav);
    await delay(300);
    const paused = await mpv.get("pause");
    if (paused) {
      await mpv.pause(false);
      await delay(200);
    }
    await mpv.seekAbsolute(2);
    await delay(150);
    const pos = await mpv.get("time-pos");
    assert.ok(pos >= 1.7 && pos <= 3.0, `expected ~2s, got ${pos}`);
  } finally {
    await mpv.quit();
  }
});
