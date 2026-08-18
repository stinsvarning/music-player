import { COMMANDS, commandRisk } from "./commands.js";
import { requestEngine } from "./ctl.js";

const SKIP = new Set(["help", "commands"]);
const SUPPORTED_VERSIONS = ["2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"];

export function toolNameFor(cmd) {
  return String(cmd).replaceAll(".", "_");
}

export function cmdFromTool(name) {
  const want = String(name || "");
  const hit = COMMANDS.find((row) => row.cmd === want || toolNameFor(row.cmd) === want);
  return hit ? hit.cmd : null;
}

export function mcpAllowDangerous() {
  const flag = String(process.env.MUSIC_PLAYER_MCP_DANGEROUS || "").toLowerCase();
  return flag === "1" || flag === "on" || flag === "true" || flag === "yes";
}

export function mcpTools({ allowDangerous = false } = {}) {
  return COMMANDS.filter((row) => {
    if (SKIP.has(row.cmd)) {
      return false;
    }
    if (row.risk === "dangerous" && !allowDangerous) {
      return false;
    }
    return true;
  }).map((row) => ({
    name: toolNameFor(row.cmd),
    title: row.cmd,
    description: `${row.summary} (engine cmd: ${row.cmd}, risk: ${row.risk})`,
    inputSchema: schemaFor(row),
    annotations: {
      readOnlyHint: row.risk === "read",
      destructiveHint: row.risk === "dangerous",
      openWorldHint: false,
    },
  }));
}

function schemaFor(row) {
  const properties = {};
  const required = [];
  for (const arg of row.args) {
    properties[arg.name] = jsonType(arg);
    if (arg.required) {
      required.push(arg.name);
    }
  }
  const schema = { type: "object", properties };
  if (required.length) {
    schema.required = required;
  }
  return schema;
}

function jsonType(arg) {
  if (arg.type === "object" && arg.name === "track") {
    return {
      type: "object",
      additionalProperties: true,
      properties: {
        id: { type: "string" },
        title: { type: "string" },
        artist: { type: "string" },
      },
    };
  }
  if (arg.type === "object") {
    return { type: "object", additionalProperties: true };
  }
  if (arg.type === "boolean") {
    return { type: "boolean" };
  }
  if (arg.type === "number") {
    return { type: "number" };
  }
  return { type: "string" };
}

function rpcResult(id, result) {
  return { jsonrpc: "2.0", id, result };
}

function rpcError(id, code, message) {
  return { jsonrpc: "2.0", id, error: { code, message } };
}

export async function handleMcp(message, { callEngine, allowDangerous = false } = {}) {
  if (!message || typeof message !== "object") {
    return null;
  }
  const { id, method } = message;
  if (!method) {
    return null;
  }
  if (method.startsWith("notifications/")) {
    return null;
  }
  if (method === "initialize") {
    const asked = message.params?.protocolVersion;
    const protocolVersion = SUPPORTED_VERSIONS.includes(asked) ? asked : "2025-03-26";
    return rpcResult(id, {
      protocolVersion,
      capabilities: { tools: { listChanged: false } },
      serverInfo: { name: "music-player", version: "0.1.0" },
    });
  }
  if (method === "ping") {
    return rpcResult(id, {});
  }
  if (method === "tools/list") {
    return rpcResult(id, { tools: mcpTools({ allowDangerous }) });
  }
  if (method === "tools/call") {
    const name = message.params?.name;
    const raw = message.params?.arguments;
    const args = raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};
    const cmd = cmdFromTool(name);
    if (!cmd || (commandRisk(cmd) === "dangerous" && !allowDangerous)) {
      return rpcError(id, -32602, `Unknown tool: ${name}`);
    }
    const call = callEngine || ((payload) => requestEngine(payload));
    let resp;
    try {
      resp = await call({ ...args, cmd });
    } catch (err) {
      return rpcResult(id, {
        content: [{ type: "text", text: String(err.message || err) }],
        isError: true,
      });
    }
    const result = {
      content: [{ type: "text", text: JSON.stringify(resp) }],
      isError: !resp || resp.ok === false,
    };
    if (resp && typeof resp === "object") {
      result.structuredContent = resp;
    }
    return rpcResult(id, result);
  }
  return rpcError(id, -32601, `Method not found: ${method}`);
}

export async function runMcpStdio({ stdin, stdout, stderr, callEngine, allowDangerous } = {}) {
  const input = stdin || process.stdin;
  const output = stdout || process.stdout;
  const log = stderr || process.stderr;
  const allow = allowDangerous ?? mcpAllowDangerous();
  let buf = "";
  input.setEncoding("utf8");
  for await (const chunk of input) {
    buf += chunk;
    while (buf.includes("\n")) {
      const idx = buf.indexOf("\n");
      const line = buf.slice(0, idx).trim();
      buf = buf.slice(idx + 1);
      if (!line) {
        continue;
      }
      let msg;
      try {
        msg = JSON.parse(line);
      } catch (err) {
        log.write(`invalid JSON: ${err.message}\n`);
        continue;
      }
      const reply = await handleMcp(msg, { callEngine, allowDangerous: allow });
      if (reply) {
        output.write(`${JSON.stringify(reply)}\n`);
      }
    }
  }
}
