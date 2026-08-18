import assert from "node:assert/strict";
import { test } from "node:test";
import { COMMANDS } from "../src/commands.js";
import { cmdFromTool, handleMcp, mcpTools, toolNameFor } from "../src/mcp.js";
import { listen } from "../src/server.js";
import { requestEngine } from "../src/ctl.js";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

test("tool names are underscore forms of catalog cmds", () => {
  assert.equal(toolNameFor("queue.list"), "queue_list");
  assert.equal(cmdFromTool("queue_list"), "queue.list");
  assert.equal(cmdFromTool("status"), "status");
});

test("mcpTools covers every safe catalog command and skips help", () => {
  const tools = mcpTools();
  const names = new Set(tools.map((t) => t.name));
  assert.equal(names.has("help"), false);
  assert.equal(names.has("commands"), false);
  assert.equal(names.has("shutdown"), false);
  assert.equal(names.has("auth_refresh"), false);
  assert.ok(names.has("status"));
  assert.ok(names.has("search"));
  assert.ok(names.has("track_play"));
  assert.ok(names.has("queue_save"));
  for (const row of COMMANDS) {
    if (row.cmd === "help" || row.cmd === "commands" || row.risk === "dangerous") {
      continue;
    }
    assert.ok(names.has(toolNameFor(row.cmd)), `missing tool for ${row.cmd}`);
  }
  const search = tools.find((t) => t.name === "search");
  assert.equal(search.inputSchema.required.includes("query"), true);
  assert.equal(search.annotations.readOnlyHint, true);
});

test("mcpTools includes dangerous cmds only when asked", () => {
  const names = mcpTools({ allowDangerous: true }).map((t) => t.name);
  assert.ok(names.includes("shutdown"));
  assert.ok(names.includes("auth_refresh"));
});

test("handleMcp initialize advertises tools", async () => {
  const resp = await handleMcp({
    jsonrpc: "2.0",
    id: 1,
    method: "initialize",
    params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "test" } },
  });
  assert.equal(resp.id, 1);
  assert.equal(resp.result.capabilities.tools.listChanged, false);
  assert.equal(resp.result.serverInfo.name, "music-player");
  assert.equal(resp.result.protocolVersion, "2025-06-18");
});

test("handleMcp tools/list returns the catalog as tools", async () => {
  const resp = await handleMcp({ jsonrpc: "2.0", id: 2, method: "tools/list" });
  assert.ok(resp.result.tools.some((t) => t.name === "status"));
  assert.ok(!resp.result.tools.some((t) => t.name === "shutdown"));
});

test("handleMcp tools/call forwards to the engine", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "music-mcp-"));
  const sock = path.join(dir, "engine.sock");
  const server = await listen(sock, async (req) => ({ ok: true, echo: req.cmd, query: req.query }));
  try {
    const resp = await handleMcp(
      {
        jsonrpc: "2.0",
        id: 3,
        method: "tools/call",
        params: { name: "search", arguments: { query: "suede" } },
      },
      { callEngine: (payload) => requestEngine(payload, sock, 2000) },
    );
    assert.equal(resp.result.isError, false);
    const body = JSON.parse(resp.result.content[0].text);
    assert.equal(body.echo, "search");
    assert.equal(body.query, "suede");
  } finally {
    await new Promise((r) => server.close(r));
  }
});

test("handleMcp tools/call marks engine failures as tool errors", async () => {
  const resp = await handleMcp(
    { jsonrpc: "2.0", id: 4, method: "tools/call", params: { name: "status", arguments: {} } },
    { callEngine: async () => ({ ok: false, error: "engine down" }) },
  );
  assert.equal(resp.result.isError, true);
  assert.match(resp.result.content[0].text, /engine down/);
});

test("handleMcp tools/call ignores a cmd override in arguments", async () => {
  let seen = null;
  const resp = await handleMcp(
    {
      jsonrpc: "2.0",
      id: 7,
      method: "tools/call",
      params: { name: "status", arguments: { cmd: "shutdown" } },
    },
    {
      callEngine: async (payload) => {
        seen = payload;
        return { ok: true };
      },
    },
  );
  assert.equal(resp.result.isError, false);
  assert.equal(seen.cmd, "status");
});

test("handleMcp refuses unknown and dangerous tools", async () => {
  const unknown = await handleMcp({
    jsonrpc: "2.0",
    id: 5,
    method: "tools/call",
    params: { name: "explode", arguments: {} },
  });
  assert.equal(unknown.error.code, -32602);
  const danger = await handleMcp({
    jsonrpc: "2.0",
    id: 6,
    method: "tools/call",
    params: { name: "shutdown", arguments: {} },
  });
  assert.equal(danger.error.code, -32602);
});

test("initialized notification has no reply", async () => {
  const resp = await handleMcp({ jsonrpc: "2.0", method: "notifications/initialized" });
  assert.equal(resp, null);
});
