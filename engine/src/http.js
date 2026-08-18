import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import { commandRisk } from "./commands.js";
import { attachId, fail, parseRequest } from "./protocol.js";

const MAX_BODY = 1_000_000;
const LOOPBACK = new Set(["127.0.0.1", "::1", "localhost"]);

export function generateToken() {
  return crypto.randomBytes(32).toString("hex");
}

export function tokensEqual(left, right) {
  const a = crypto.createHash("sha256").update(String(left ?? ""), "utf8").digest();
  const b = crypto.createHash("sha256").update(String(right ?? ""), "utf8").digest();
  return crypto.timingSafeEqual(a, b);
}

export function loadOrCreateToken(filePath) {
  try {
    if (fs.existsSync(filePath)) {
      const existing = fs.readFileSync(filePath, "utf8").trim();
      if (existing) {
        return existing;
      }
    }
  } catch {
    /* recreate */
  }
  const token = generateToken();
  fs.writeFileSync(filePath, `${token}\n`, { encoding: "utf8", mode: 0o600 });
  try {
    fs.chmodSync(filePath, 0o600);
  } catch {
    /* umask already applied */
  }
  return token;
}

export function readToken(req) {
  const auth = req.headers.authorization;
  if (typeof auth === "string") {
    const match = /^Bearer\s+(.+)$/i.exec(auth.trim());
    if (match) {
      return match[1].trim();
    }
  }
  const alt = req.headers["x-music-player-token"];
  if (typeof alt === "string" && alt.trim()) {
    return alt.trim();
  }
  return "";
}

export function assertLoopbackHost(host) {
  if (!LOOPBACK.has(String(host || ""))) {
    throw new Error("http bind must be loopback");
  }
}

function isLoopbackAddress(addr) {
  const trimmed = String(addr || "").replace(/^::ffff:/, "");
  return LOOPBACK.has(trimmed);
}

function send(res, status, body) {
  const json = JSON.stringify(body);
  res.writeHead(status, {
    "content-type": "application/json",
    "cache-control": "no-store",
  });
  res.end(json);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const declared = Number(req.headers["content-length"] || 0);
    if (declared > MAX_BODY) {
      reject(Object.assign(new Error("payload too large"), { status: 413 }));
      return;
    }
    const chunks = [];
    let size = 0;
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY) {
        req.destroy();
        reject(Object.assign(new Error("payload too large"), { status: 413 }));
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

export function createHttpHandler({ token, handler, allowDangerous = false }) {
  if (!token) {
    throw new Error("http token is required");
  }
  return async (req, res) => {
    if (!isLoopbackAddress(req.socket.remoteAddress)) {
      send(res, 403, fail("loopback only"));
      return;
    }
    if (!tokensEqual(readToken(req), token)) {
      send(res, 401, fail("unauthorized"));
      return;
    }
    if (req.method === "GET") {
      send(res, 200, { ok: true, transport: "http" });
      return;
    }
    if (req.method !== "POST") {
      send(res, 405, fail("POST only"));
      return;
    }
    let raw;
    try {
      raw = await readBody(req);
    } catch (err) {
      send(res, err.status || 400, fail(err.message || err));
      return;
    }
    const parsed = parseRequest(raw);
    if (!parsed.ok) {
      send(res, 400, fail(parsed.error));
      return;
    }
    if (!allowDangerous && commandRisk(parsed.request.cmd) === "dangerous") {
      send(res, 403, attachId(parsed.request, fail("dangerous command blocked on http")));
      return;
    }
    let resp;
    try {
      resp = await handler(parsed.request);
    } catch (err) {
      resp = fail(err.message || err);
    }
    send(res, 200, attachId(parsed.request, resp));
  };
}

export function listenHttp({
  port = 0,
  host = "127.0.0.1",
  token,
  handler,
  allowDangerous = false,
} = {}) {
  try {
    assertLoopbackHost(host);
  } catch (err) {
    return Promise.reject(err);
  }
  const server = http.createServer(createHttpHandler({ token, handler, allowDangerous }));
  return new Promise((resolve, reject) => {
    const onError = (err) => {
      server.off("listening", onListening);
      reject(err);
    };
    const onListening = () => {
      server.off("error", onError);
      resolve(server);
    };
    server.once("error", onError);
    server.once("listening", onListening);
    server.listen(port, host);
  });
}
