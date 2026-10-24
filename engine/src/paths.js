import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export function configDir() {
  const base = process.env.XDG_CONFIG_HOME || path.join(os.homedir(), ".config");
  return path.join(base, "music-player");
}

export function engineSocket() {
  return process.env.MUSIC_PLAYER_SOCK || path.join(configDir(), "engine.sock");
}

export function engineLockPath() {
  return process.env.MUSIC_PLAYER_LOCK || path.join(configDir(), "engine.lock");
}

export function mpvSocket() {
  return process.env.MUSIC_PLAYER_MPV_SOCK || path.join(configDir(), "mpv.sock");
}

export function runtimeDir(env = process.env) {
  const base = env.XDG_RUNTIME_DIR || os.tmpdir();
  return path.join(base, "music-player");
}

export function spectrumDir(env = process.env) {
  if (env.MUSIC_PLAYER_SPEC) {
    return env.MUSIC_PLAYER_SPEC;
  }
  return path.join(runtimeDir(env), "spectrum");
}

export function innertubeCacheDir(env = process.env) {
  return env.MUSIC_PLAYER_INNERTUBE_CACHE || path.join(configDir(), "innertube");
}

export function configPath() {
  return path.join(configDir(), "config.toml");
}

export function ensureConfigDir() {
  fs.mkdirSync(configDir(), { recursive: true, mode: 0o700 });
}

export function readCookiesFromSetting() {
  if (!fs.existsSync(configPath())) {
    return "auto";
  }
  const text = fs.readFileSync(configPath(), "utf8");
  for (const raw of text.split("\n")) {
    const line = raw.split("#", 1)[0].trim();
    if (line.toLowerCase().startsWith("cookies_from")) {
      const [, val] = line.split("=");
      return (val || "").trim().replace(/^["']|["']$/g, "") || "auto";
    }
  }
  return "auto";
}

export function savedCookiesPath() {
  return path.join(configDir(), "cookies.header");
}

export function signedOutPath() {
  return process.env.MUSIC_PLAYER_SIGNED_OUT || path.join(configDir(), "signed-out");
}

export function urlCachePath() {
  return process.env.MUSIC_PLAYER_URL_CACHE || path.join(configDir(), "url-cache.json");
}

export function httpTokenPath() {
  return process.env.MUSIC_PLAYER_HTTP_TOKEN_FILE || path.join(configDir(), "http.token");
}

export function httpPort() {
  const raw = process.env.MUSIC_PLAYER_HTTP_PORT;
  if (raw == null || raw === "") {
    return 18741;
  }
  const n = Number(raw);
  if (!Number.isInteger(n) || n < 0 || n > 65535) {
    return 18741;
  }
  return n;
}

export function httpEnabled() {
  const flag = String(process.env.MUSIC_PLAYER_HTTP ?? "on").toLowerCase();
  if (flag === "0" || flag === "off" || flag === "false" || flag === "no") {
    return false;
  }
  return httpPort() > 0;
}

export function httpUrl() {
  return `http://127.0.0.1:${httpPort()}/`;
}

export function httpAllowDangerous() {
  const flag = String(process.env.MUSIC_PLAYER_HTTP_DANGEROUS || "").toLowerCase();
  return flag === "1" || flag === "on" || flag === "true" || flag === "yes";
}
