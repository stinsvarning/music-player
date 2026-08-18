import assert from "node:assert/strict";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { listen } from "../src/server.js";

function tmpSock() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "music-listen-"));
  return path.join(dir, "engine.sock");
}

function readLines(sock, count) {
  return new Promise((resolve, reject) => {
    let buf = "";
    const lines = [];
    const onData = (chunk) => {
      buf += chunk.toString();
      while (buf.includes("\n")) {
        const idx = buf.indexOf("\n");
        lines.push(JSON.parse(buf.slice(0, idx)));
        buf = buf.slice(idx + 1);
        if (lines.length >= count) {
          sock.off("data", onData);
          resolve(lines);
        }
      }
    };
    sock.on("data", onData);
    sock.on("error", reject);
    setTimeout(() => reject(new Error("timed out waiting for replies")), 2000);
  });
}

test("listen refuses to steal a live engine socket", async () => {
  const socketPath = tmpSock();
  const first = await listen(socketPath, async () => ({ ok: true, owner: 1 }));
  try {
    await assert.rejects(() => listen(socketPath, async () => ({ ok: true, owner: 2 })), /already listening/);
    const client = net.createConnection(socketPath);
    await new Promise((r) => client.once("connect", r));
    client.write('{"cmd":"status"}\n');
    const [line] = await readLines(client, 1);
    client.end();
    assert.equal(line.owner, 1);
  } finally {
    await new Promise((r) => first.close(r));
  }
});

test("listen replaces a stale leftover socket", async () => {
  const socketPath = tmpSock();
  const stale = await listen(socketPath, async () => ({ ok: true, owner: "old" }));
  await new Promise((r) => stale.close(r));
  const live = await listen(socketPath, async () => ({ ok: true, owner: "new" }));
  const client = net.createConnection(socketPath);
  await new Promise((r) => client.once("connect", r));
  client.write('{"cmd":"status"}\n');
  const [line] = await readLines(client, 1);
  client.end();
  await new Promise((r) => live.close(r));
  assert.equal(line.owner, "new");
});

test("listen handles one connection's requests in order", async () => {
  const socketPath = tmpSock();
  let inflight = 0;
  let peak = 0;
  const server = await listen(socketPath, async (req) => {
    inflight += 1;
    peak = Math.max(peak, inflight);
    await new Promise((r) => setTimeout(r, 40));
    inflight -= 1;
    return { ok: true, n: req.n };
  });
  const client = net.createConnection(socketPath);
  await new Promise((r) => client.once("connect", r));
  client.write('{"cmd":"x","n":1}\n');
  await new Promise((r) => setTimeout(r, 10));
  client.write('{"cmd":"x","n":2}\n');
  const lines = await readLines(client, 2);
  client.end();
  await new Promise((r) => server.close(r));
  assert.equal(peak, 1);
  assert.equal(lines[0].n, 1);
  assert.equal(lines[1].n, 2);
});
