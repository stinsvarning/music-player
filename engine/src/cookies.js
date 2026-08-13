import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

function expandHome(p) {
  if (p.startsWith("~/")) {
    return path.join(os.homedir(), p.slice(2));
  }
  return p;
}

export function parseCookiesFrom(spec) {
  const raw = spec || "firefox:~/.config/zen";
  const [browser, loc] = raw.split(":");
  return { browser: (browser || "firefox").trim(), profileDir: loc ? expandHome(loc.trim()) : "" };
}

export function readCookieHeader(spec) {
  const { profileDir } = parseCookiesFrom(spec);
  const header = slimCookieHeader(fromSqlite(profileDir));
  if (header.includes("LOGIN_INFO=") || header.includes("SAPISID=")) {
    return header;
  }
  return slimCookieHeader(fromYtdlpDump(spec));
}

const KEEP = new Set([
  "SAPISID",
  "APISID",
  "HSID",
  "SSID",
  "SID",
  "SIDCC",
  "LOGIN_INFO",
  "PREF",
  "VISITOR_INFO1_LIVE",
  "YSC",
  "CONSENT",
  "SOCS",
  "__Secure-1PSID",
  "__Secure-3PSID",
  "__Secure-1PAPISID",
  "__Secure-3PAPISID",
  "__Secure-1PSIDTS",
  "__Secure-3PSIDTS",
  "__Secure-1PSIDCC",
  "__Secure-3PSIDCC",
  "__Secure-YNID",
]);

function slimCookieHeader(header) {
  const byName = new Map();
  for (const part of String(header || "").split(";")) {
    const trimmed = part.trim();
    if (!trimmed || !trimmed.includes("=")) {
      continue;
    }
    const name = trimmed.slice(0, trimmed.indexOf("="));
    if (!KEEP.has(name) && !name.startsWith("__Secure-")) {
      continue;
    }
    if (KEEP.has(name) || name.startsWith("__Secure-1P") || name.startsWith("__Secure-3P")) {
      byName.set(name, trimmed);
    }
  }
  return [...byName.values()].join("; ");
}

function findProfile(profileDir) {
  if (!profileDir || !fs.existsSync(profileDir)) {
    return "";
  }
  const direct = path.join(profileDir, "cookies.sqlite");
  if (fs.existsSync(direct)) {
    return profileDir;
  }
  const entries = fs.readdirSync(profileDir, { withFileTypes: true });
  for (const ent of entries) {
    if (!ent.isDirectory()) {
      continue;
    }
    const candidate = path.join(profileDir, ent.name, "cookies.sqlite");
    if (fs.existsSync(candidate)) {
      return path.join(profileDir, ent.name);
    }
  }
  return "";
}

function fromSqlite(profileDir) {
  const profile = findProfile(profileDir);
  if (!profile) {
    return "";
  }
  const src = path.join(profile, "cookies.sqlite");
  const tmp = path.join(os.tmpdir(), `music-player-cookies-${process.pid}.sqlite`);
  fs.copyFileSync(src, tmp);
  for (const suffix of ["-wal", "-shm"]) {
    const extra = src + suffix;
    if (fs.existsSync(extra)) {
      try {
        fs.copyFileSync(extra, tmp + suffix);
      } catch {
        /* ignore */
      }
    }
  }
  let out = "";
  try {
    out = execFileSync(
      "sqlite3",
      [
        tmp,
        "SELECT name || '=' || value FROM moz_cookies WHERE host LIKE '%youtube%' OR host LIKE '%google.com%' ORDER BY host;",
      ],
      { encoding: "utf8" },
    );
  } finally {
    for (const p of [tmp, tmp + "-wal", tmp + "-shm"]) {
      try {
        fs.unlinkSync(p);
      } catch {
        /* ignore */
      }
    }
  }
  return out
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .join("; ");
}

function fromYtdlpDump(spec) {
  const { browser, profileDir } = parseCookiesFrom(spec);
  const browserArg = profileDir ? `${browser}:${profileDir}` : browser;
  const dest = path.join(os.tmpdir(), `music-player-cookies-${process.pid}.txt`);
  try {
    execFileSync(
      "yt-dlp",
      [
        "--cookies-from-browser",
        browserArg,
        "--cookies",
        dest,
        "--skip-download",
        "--no-warnings",
        "--ignore-no-formats-error",
        "https://www.youtube.com",
      ],
      { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], timeout: 30000 },
    );
  } catch {
    /* dump file may still exist */
  }
  if (!fs.existsSync(dest)) {
    return "";
  }
  const parts = [];
  for (const line of fs.readFileSync(dest, "utf8").split("\n")) {
    if (!line || line.startsWith("#")) {
      continue;
    }
    const cols = line.split("\t");
    if (cols.length < 7) {
      continue;
    }
    const domain = cols[0];
    if (!domain.includes("youtube") && !domain.includes("google")) {
      continue;
    }
    parts.push(`${cols[5]}=${cols[6]}`);
  }
  try {
    fs.unlinkSync(dest);
  } catch {
    /* ignore */
  }
  return parts.join("; ");
}
