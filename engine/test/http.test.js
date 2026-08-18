import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { loadOrCreateToken, listenHttp, tokensEqual } from "../src/http.js";

function tokenFile() {
  return path.join(fs.mkdtempSync(path.join(os.tmpdir(), "music-http-")), "http.token");
}

async function withServer(opts, fn) {
  const server = await listenHttp({
    host: "127.0.0.1",
    port: 0,
    token: "secret-token",
    handler: async (req) => ({ ok: true, echo: req.cmd, id: req.id }),
    ...opts,
  });
  const { port } = server.address();
  try {
    await fn({ server, port, url: `http://127.0.0.1:${port}/` });
  } finally {
    await new Promise((r) => server.close(r));
  }
}

function post(url, { token, body, method = "POST", header } = {}) {
  const headers = { "content-type": "application/json" };
  if (token) {
    headers.authorization = `Bearer ${token}`;
  }
  if (header) {
    Object.assign(headers, header);
  }
  return fetch(url, {
    method,
    headers,
    body: method === "GET" ? undefined : JSON.stringify(body ?? { cmd: "status" }),
  });
}

test("tokensEqual is true only for the same secret", () => {
  assert.equal(tokensEqual("abc", "abc"), true);
  assert.equal(tokensEqual("abc", "abd"), false);
  assert.equal(tokensEqual("abc", ""), false);
});

test("loadOrCreateToken writes mode 600 and reuses the file", () => {
  const file = tokenFile();
  const first = loadOrCreateToken(file);
  const second = loadOrCreateToken(file);
  assert.equal(first.length >= 32, true);
  assert.equal(second, first);
  assert.equal(fs.statSync(file).mode & 0o777, 0o600);
});

test("listenHttp refuses a non-loopback bind", async () => {
  await assert.rejects(
    () =>
      listenHttp({
        host: "0.0.0.0",
        port: 0,
        token: "x",
        handler: async () => ({ ok: true }),
      }),
    /loopback/,
  );
});

test("listenHttp binds 127.0.0.1", async () => {
  await withServer({}, async ({ server }) => {
    assert.equal(server.address().address, "127.0.0.1");
  });
});

test("missing or wrong token is 401", async () => {
  await withServer({}, async ({ url }) => {
    const none = await post(url, {});
    assert.equal(none.status, 401);
    assert.equal((await none.json()).ok, false);
    const bad = await post(url, { token: "nope" });
    assert.equal(bad.status, 401);
  });
});

test("Bearer token runs the same JSON command", async () => {
  await withServer({}, async ({ url }) => {
    const resp = await post(url, { token: "secret-token", body: { cmd: "status", id: 9 } });
    assert.equal(resp.status, 200);
    const json = await resp.json();
    assert.deepEqual(json, { ok: true, echo: "status", id: 9 });
  });
});

test("X-Music-Player-Token is accepted", async () => {
  await withServer({}, async ({ url }) => {
    const resp = await post(url, {
      header: { "x-music-player-token": "secret-token" },
      body: { cmd: "next" },
    });
    assert.equal(resp.status, 200);
    assert.equal((await resp.json()).echo, "next");
  });
});

test("GET with a token is a cheap ping, PUT is rejected", async () => {
  await withServer({}, async ({ url }) => {
    const ping = await post(url, { token: "secret-token", method: "GET" });
    assert.equal(ping.status, 200);
    assert.deepEqual(await ping.json(), { ok: true, transport: "http" });
    const put = await post(url, { token: "secret-token", method: "PUT" });
    assert.equal(put.status, 405);
  });
});

test("shutdown and auth.refresh are blocked on http", async () => {
  await withServer({}, async ({ url }) => {
    for (const cmd of ["shutdown", "auth.refresh"]) {
      const resp = await post(url, { token: "secret-token", body: { cmd } });
      assert.equal(resp.status, 403);
      const json = await resp.json();
      assert.equal(json.ok, false);
      assert.match(json.error, /dangerous/);
    }
  });
});

test("dangerous commands pass when allowDangerous is set", async () => {
  await withServer({ allowDangerous: true, handler: async (req) => ({ ok: true, cmd: req.cmd }) }, async ({ url }) => {
    const resp = await post(url, { token: "secret-token", body: { cmd: "shutdown" } });
    assert.equal(resp.status, 200);
    assert.equal((await resp.json()).cmd, "shutdown");
  });
});
