import assert from "node:assert/strict";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { encode, ok } from "../src/protocol.js";
import { acquireLock, pidAlive, pingEngine, releaseLock } from "../src/singleton.js";

test("pidAlive is true for this process and false for a dead pid", () => {
  assert.equal(pidAlive(process.pid), true);
  assert.equal(pidAlive(1_000_000_007), false);
  assert.equal(pidAlive(0), false);
});

test("acquireLock is exclusive and stealable from a dead pid", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "music-lock-"));
  const lockPath = path.join(dir, "engine.lock");
  const first = acquireLock(lockPath);
  assert.ok(first);
  assert.equal(acquireLock(lockPath), null);
  releaseLock(first);
  fs.writeFileSync(lockPath, "1000000007\n");
  const stolen = acquireLock(lockPath);
  assert.ok(stolen);
  releaseLock(stolen);
});

test("pingEngine returns true only when a live engine answers status", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "music-sock-"));
  const sockPath = path.join(dir, "engine.sock");
  assert.equal(await pingEngine(sockPath), false);
  const server = net.createServer((sock) => {
    sock.on("data", () => sock.write(encode(ok({ state: "stopped" }))));
  });
  await new Promise((resolve) => server.listen(sockPath, resolve));
  try {
    assert.equal(await pingEngine(sockPath), true);
  } finally {
    server.close();
  }
});
