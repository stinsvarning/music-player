import assert from "node:assert/strict";
import { test } from "node:test";
import { parseCtlArgs, runCtl } from "../src/ctl.js";
import { listenHttp } from "../src/http.js";
import { listen } from "../src/server.js";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

test("parseCtlArgs maps help status search play next", () => {
  assert.deepEqual(parseCtlArgs([]), { cmd: "help" });
  assert.deepEqual(parseCtlArgs(["help"]), { cmd: "help" });
  assert.deepEqual(parseCtlArgs(["status"]), { cmd: "status" });
  assert.deepEqual(parseCtlArgs(["search", "suede", "animal"]), { cmd: "search", query: "suede animal" });
  assert.deepEqual(parseCtlArgs(["play", "--id", "abc"]), { cmd: "track.play", track: { id: "abc" } });
  assert.deepEqual(parseCtlArgs(["next"]), { cmd: "next" });
  assert.deepEqual(parseCtlArgs(["--json", '{"cmd":"volume","value":40}']), { cmd: "volume", value: 40 });
  assert.deepEqual(parseCtlArgs(["--http", "status"]), { cmd: "status" });
});

test("runCtl prints help JSON from a live socket", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "music-ctl-"));
  const sock = path.join(dir, "engine.sock");
  const server = await listen(sock, async (req) => {
    if (req.cmd === "help") {
      return { ok: true, commands: [{ cmd: "status", risk: "read" }] };
    }
    return { ok: true, echo: req.cmd };
  });
  const prev = process.env.MUSIC_PLAYER_SOCK;
  process.env.MUSIC_PLAYER_SOCK = sock;
  try {
    const { code, out } = await runCtl(["help"]);
    assert.equal(code, 0);
    const json = JSON.parse(out);
    assert.equal(json.ok, true);
    assert.equal(json.commands[0].cmd, "status");
  } finally {
    if (prev === undefined) {
      delete process.env.MUSIC_PLAYER_SOCK;
    } else {
      process.env.MUSIC_PLAYER_SOCK = prev;
    }
    await new Promise((r) => server.close(r));
  }
});

test("runCtl --http posts JSON to the loopback front", async () => {
  const server = await listenHttp({
    host: "127.0.0.1",
    port: 0,
    token: "ctl-token",
    handler: async () => ({ ok: true, commands: [{ cmd: "status", risk: "read" }] }),
  });
  const { port } = server.address();
  try {
    const { code, out } = await runCtl(["--http", "help"], {
      httpUrl: `http://127.0.0.1:${port}/`,
      httpToken: "ctl-token",
    });
    assert.equal(code, 0);
    assert.equal(JSON.parse(out).commands[0].cmd, "status");
  } finally {
    await new Promise((r) => server.close(r));
  }
});
