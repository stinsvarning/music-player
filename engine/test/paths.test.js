import assert from "node:assert/strict";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { mprisEnabled, mpvExtraArgs, runtimeDir, spectrumDir } from "../src/paths.js";

test("spectrum logs follow XDG_RUNTIME_DIR", () => {
  const env = { XDG_RUNTIME_DIR: "/run/user/1000" };
  assert.equal(runtimeDir(env), path.join("/run/user/1000", "music-player"));
  assert.equal(spectrumDir(env), path.join("/run/user/1000", "music-player", "spectrum"));
});

test("spectrum logs fall back to the tmp dir", () => {
  assert.equal(spectrumDir({}), path.join(os.tmpdir(), "music-player", "spectrum"));
});

test("MUSIC_PLAYER_SPEC still overrides the runtime dir", () => {
  assert.equal(spectrumDir({ MUSIC_PLAYER_SPEC: "/var/tmp/spec", XDG_RUNTIME_DIR: "/run/user/1" }), "/var/tmp/spec");
});

test("headless knobs: extra mpv args and mpris off", () => {
  assert.deepEqual(mpvExtraArgs({ MUSIC_PLAYER_MPV_ARGS: " --ao=null  --volume=0 " }), ["--ao=null", "--volume=0"]);
  assert.deepEqual(mpvExtraArgs({}), []);
  assert.equal(mprisEnabled({}), true);
  assert.equal(mprisEnabled({ MUSIC_PLAYER_NO_MPRIS: "1" }), false);
});
