import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const LOGIN_REQUIRED = "LOGIN_REQUIRED: log in to YouTube Music in a browser on this computer";

function expandHome(p, home = os.homedir()) {
  if (!p) {
    return "";
  }
  if (p === "~") {
    return home;
  }
  if (p.startsWith("~/")) {
    return path.join(home, p.slice(2));
  }
  return p;
}

export function parseCookiesFrom(spec, home = os.homedir()) {
  const raw = spec || "auto";
  const idx = raw.indexOf(":");
  if (idx < 0) {
    return { browser: raw.trim() || "auto", profileDir: "" };
  }
  return {
    browser: raw.slice(0, idx).trim() || "auto",
    profileDir: expandHome(raw.slice(idx + 1).trim(), home),
  };
}

export function hasYoutubeSession(header) {
  return /(?:^|;\s*)(LOGIN_INFO|SAPISID)=/.test(String(header || ""));
}

export function defaultBrowserCandidates(home) {
  const root = home || os.homedir();
  return [
    { browser: "firefox", profileDir: path.join(root, ".config/zen") },
    { browser: "firefox", profileDir: path.join(root, ".var/app/app.zen_browser.zen/.zen") },
    { browser: "firefox", profileDir: path.join(root, ".mozilla/firefox") },
    { browser: "firefox", profileDir: path.join(root, ".var/app/org.mozilla.firefox/.mozilla/firefox") },
    { browser: "firefox", profileDir: path.join(root, ".librewolf") },
    { browser: "chrome", profileDir: path.join(root, ".config/google-chrome") },
    { browser: "chromium", profileDir: path.join(root, ".config/chromium") },
    { browser: "chrome", profileDir: path.join(root, ".config/BraveSoftware/Brave-Browser") },
    { browser: "chrome", profileDir: path.join(root, ".config/microsoft-edge") },
    { browser: "chrome", profileDir: path.join(root, ".config/vivaldi") },
    { browser: "chrome", profileDir: path.join(root, ".config/helium") },
  ];
}

export function slimCookieHeader(header) {
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

export function clearSavedHeader(filePath) {
  if (!filePath) {
    return;
  }
  try {
    fs.unlinkSync(filePath);
  } catch {
    /* missing is fine */
  }
}

export function isSignedOut(filePath) {
  return Boolean(filePath && fs.existsSync(filePath));
}

export function markSignedOut(filePath) {
  if (!filePath) {
    return;
  }
  fs.mkdirSync(path.dirname(filePath), { recursive: true, mode: 0o700 });
  fs.writeFileSync(filePath, "1\n", { mode: 0o600 });
}

export function clearSignedOut(filePath) {
  clearSavedHeader(filePath);
}

export function writeSavedHeader(filePath, header) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true, mode: 0o700 });
  fs.writeFileSync(filePath, `${slimCookieHeader(header)}\n`, { mode: 0o600 });
}

export function readSavedHeader(filePath) {
  if (!filePath || !fs.existsSync(filePath)) {
    return "";
  }
  const text = fs.readFileSync(filePath, "utf8");
  if (text.includes("\t") && /netscape|http.*true\/false/i.test(text)) {
    return netscapeToHeader(text);
  }
  return text.trim();
}

function netscapeToHeader(text) {
  const parts = [];
  for (const line of text.split("\n")) {
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
  return parts.join("; ");
}

function commandOnPath(bin) {
  return (process.env.PATH || "").split(path.delimiter).some((dir) => {
    if (!dir) {
      return false;
    }
    try {
      return fs.existsSync(path.join(dir, bin));
    } catch {
      return false;
    }
  });
}

export function cookieScanHint(home) {
  const homeDir = home || os.homedir();
  const haveYtdlp = commandOnPath("yt-dlp");
  const haveSqlite = commandOnPath("sqlite3");
  const bits = [];
  if (fs.existsSync(path.join(homeDir, ".config/chromium")) && !haveYtdlp) {
    bits.push("Chromium needs yt-dlp (pacman -S yt-dlp)");
  }
  if (
    fs.existsSync(path.join(homeDir, ".mozilla/firefox")) &&
    !haveSqlite &&
    !haveYtdlp
  ) {
    bits.push("Firefox needs sqlite or yt-dlp (pacman -S sqlite yt-dlp)");
  }
  if (bits.length) {
    return `${LOGIN_REQUIRED}. ${bits.join(". ")}.`;
  }
  return LOGIN_REQUIRED;
}

export function resolveCookies({ spec, home, savedPath, readSaved, readBrowser, skipSaved = false } = {}) {
  const homeDir = home || os.homedir();
  const saved = savedPath || "";
  const loadSaved = readSaved || readSavedHeader;
  const loadBrowser = readBrowser || readBrowserSpec;

  const fromFile = (file, source) => {
    const header = slimCookieHeader(loadSaved(file));
    return hasYoutubeSession(header) ? { header, source } : null;
  };

  const fromSpec = (raw) => {
    if (!raw || raw === "auto" || raw === "saved") {
      return null;
    }
    if (raw.startsWith("file:")) {
      return fromFile(expandHome(raw.slice(5), homeDir), raw);
    }
    const header = slimCookieHeader(loadBrowser(raw, homeDir));
    return hasYoutubeSession(header) ? { header, source: raw } : null;
  };

  const explicit = fromSpec(spec);
  if (explicit) {
    return explicit;
  }
  if (saved && !skipSaved) {
    const found = fromFile(saved, "saved");
    if (found) {
      return found;
    }
  }
  if (!spec || spec === "auto" || spec === "saved") {
    for (const candidate of defaultBrowserCandidates(homeDir)) {
      if (!fs.existsSync(candidate.profileDir)) {
        continue;
      }
      const raw = `${candidate.browser}:${candidate.profileDir}`;
      const header = slimCookieHeader(loadBrowser(raw, homeDir));
      if (hasYoutubeSession(header)) {
        return { header, source: raw };
      }
    }
  }
  return { header: "", source: "", error: cookieScanHint(homeDir) };
}

export function readCookieHeader(spec) {
  return resolveCookies({ spec, savedPath: defaultSavedPath() }).header;
}

export function defaultSavedPath(home = os.homedir()) {
  const base = process.env.XDG_CONFIG_HOME || path.join(home, ".config");
  return path.join(base, "music-player", "cookies.header");
}

function readBrowserSpec(spec, home = os.homedir()) {
  const { browser, profileDir } = parseCookiesFrom(spec, home);
  if (browser === "firefox" || browser === "zen" || browser === "librewolf") {
    try {
      const fromDb = fromSqlite(profileDir);
      if (hasYoutubeSession(fromDb)) {
        return fromDb;
      }
    } catch {
      /* missing sqlite3 — fall through to yt-dlp */
    }
  }
  return fromYtdlpDump(spec, home);
}

export function firefoxDefaultProfile(profileDir) {
  if (!profileDir || !fs.existsSync(profileDir)) {
    return "";
  }
  const direct = path.join(profileDir, "cookies.sqlite");
  if (fs.existsSync(direct)) {
    return profileDir;
  }
  const fromIni = profileFromIni(profileDir);
  if (fromIni && fs.existsSync(path.join(fromIni, "cookies.sqlite"))) {
    return fromIni;
  }
  return firstCookiesProfile(profileDir);
}

function profileFromIni(profileDir) {
  const iniPath = path.join(profileDir, "profiles.ini");
  if (!fs.existsSync(iniPath)) {
    return "";
  }
  const sections = [];
  let current = { name: "", keys: {} };
  for (const raw of fs.readFileSync(iniPath, "utf8").split(/\r?\n/)) {
    const line = raw.trim();
    const heading = line.match(/^\[(.+)]$/);
    if (heading) {
      if (current.name) {
        sections.push(current);
      }
      current = { name: heading[1], keys: {} };
      continue;
    }
    const eq = line.indexOf("=");
    if (eq > 0) {
      current.keys[line.slice(0, eq).trim()] = line.slice(eq + 1).trim();
    }
  }
  if (current.name) {
    sections.push(current);
  }
  const resolve = (rel, isRelative) => {
    if (!rel) {
      return "";
    }
    if (isRelative === "0" || path.isAbsolute(rel)) {
      return rel;
    }
    return path.join(profileDir, rel);
  };
  for (const section of sections) {
    if (/^Install/i.test(section.name) && section.keys.Default) {
      return resolve(section.keys.Default, "1");
    }
  }
  for (const section of sections) {
    if (/^Profile/i.test(section.name) && section.keys.Default === "1" && section.keys.Path) {
      return resolve(section.keys.Path, section.keys.IsRelative);
    }
  }
  for (const section of sections) {
    if (/^Profile/i.test(section.name) && section.keys.Path) {
      return resolve(section.keys.Path, section.keys.IsRelative);
    }
  }
  return "";
}

function firstCookiesProfile(profileDir) {
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

function findProfile(profileDir) {
  return firefoxDefaultProfile(profileDir);
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

function fromYtdlpDump(spec, home = os.homedir()) {
  const { browser, profileDir } = parseCookiesFrom(spec, home);
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
  const header = netscapeToHeader(fs.readFileSync(dest, "utf8"));
  try {
    fs.unlinkSync(dest);
  } catch {
    /* ignore */
  }
  return header;
}
