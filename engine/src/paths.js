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

export function mpvSocket() {
  return process.env.MUSIC_PLAYER_MPV_SOCK || path.join(configDir(), "mpv.sock");
}

export function configPath() {
  return path.join(configDir(), "config.toml");
}

export function ensureConfigDir() {
  fs.mkdirSync(configDir(), { recursive: true, mode: 0o700 });
}

export function readCookiesFromSetting() {
  if (!fs.existsSync(configPath())) {
    return "firefox:~/.config/zen";
  }
  const text = fs.readFileSync(configPath(), "utf8");
  for (const raw of text.split("\n")) {
    const line = raw.split("#", 1)[0].trim();
    if (line.toLowerCase().startsWith("cookies_from")) {
      const [, val] = line.split("=");
      return (val || "").trim().replace(/^["']|["']$/g, "");
    }
  }
  return "firefox:~/.config/zen";
}
