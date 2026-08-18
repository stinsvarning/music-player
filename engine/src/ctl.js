import fs from "node:fs";
import net from "node:net";
import { encode } from "./protocol.js";
import { engineSocket, httpTokenPath, httpUrl } from "./paths.js";

export function parseCtlArgs(argv) {
  const args = argv[0] === "--http" ? argv.slice(1) : [...argv];
  if (!args.length || args[0] === "help" || args[0] === "commands") {
    return { cmd: "help" };
  }
  if (args[0] === "--json") {
    const raw = args.slice(1).join(" ").trim();
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed.cmd !== "string") {
      throw new Error("cmd is required");
    }
    return parsed;
  }
  const verb = args[0];
  const req = { cmd: verb === "play" ? "track.play" : verb };
  for (let i = 1; i < args.length; i += 1) {
    const token = args[i];
    if (token === "--id") {
      req.track = { ...(req.track || {}), id: String(args[++i] || "") };
      continue;
    }
    if (token.startsWith("--") && token.length > 2) {
      const key = token.slice(2).replace(/-/g, "_");
      req[key] = coerce(args[++i]);
      continue;
    }
    if (verb === "search") {
      req.query = args.slice(i).join(" ");
      break;
    }
  }
  return req;
}

function coerce(value) {
  if (value == null) {
    return "";
  }
  if (value === "true") {
    return true;
  }
  if (value === "false") {
    return false;
  }
  if (value !== "" && Number.isFinite(Number(value))) {
    return Number(value);
  }
  return value;
}

export function requestEngine(payload, socketPath = engineSocket(), timeoutMs = 30_000) {
  return new Promise((resolve, reject) => {
    const sock = net.createConnection(socketPath);
    let buf = "";
    const timer = setTimeout(() => {
      sock.destroy();
      reject(new Error("engine timed out"));
    }, timeoutMs);
    sock.on("connect", () => {
      sock.write(encode(payload));
    });
    sock.on("data", (chunk) => {
      buf += chunk.toString();
      if (!buf.includes("\n")) {
        return;
      }
      clearTimeout(timer);
      sock.end();
      const line = buf.split("\n", 1)[0];
      try {
        resolve(JSON.parse(line));
      } catch (err) {
        reject(err);
      }
    });
    sock.on("error", (err) => {
      clearTimeout(timer);
      reject(err);
    });
  });
}

export function readHttpToken(filePath = httpTokenPath()) {
  if (process.env.MUSIC_PLAYER_HTTP_TOKEN) {
    return process.env.MUSIC_PLAYER_HTTP_TOKEN;
  }
  return fs.readFileSync(filePath, "utf8").trim();
}

export async function requestHttp(payload, { url, token, timeoutMs } = {}) {
  const resp = await fetch(url || httpUrl(), {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(timeoutMs || 30_000),
  });
  return resp.json();
}

export async function runCtl(argv, { socketPath, timeoutMs, httpUrl: url, httpToken } = {}) {
  const req = parseCtlArgs(argv);
  const resp =
    argv[0] === "--http"
      ? await requestHttp(req, {
          url: url || httpUrl(),
          token: httpToken || readHttpToken(),
          timeoutMs: timeoutMs || 30_000,
        })
      : await requestEngine(req, socketPath || engineSocket(), timeoutMs || 30_000);
  return {
    code: resp && resp.ok === false ? 1 : 0,
    out: `${JSON.stringify(resp)}\n`,
  };
}
