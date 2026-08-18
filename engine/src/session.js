import fs from "node:fs";
import path from "node:path";
import { PRESETS } from "./eq.js";
import { configDir } from "./paths.js";

export const SESSION_VERSION = 1;

export function sessionPath() {
  return process.env.MUSIC_PLAYER_SESSION || path.join(configDir(), "session.json");
}

function storedVolume(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) {
    return 70;
  }
  return Math.max(0, Math.min(100, n));
}

function storedBands(bands) {
  const src = Array.isArray(bands) ? bands : [];
  const out = [];
  for (let i = 0; i < 10; i += 1) {
    const n = Number(src[i]);
    out.push(Number.isFinite(n) ? Math.max(-12, Math.min(12, n)) : 0);
  }
  return out;
}

function storedPreset(name, bands) {
  const label = String(name || "").trim();
  if (label === "Custom") {
    return "Custom";
  }
  if (PRESETS[label]) {
    return label;
  }
  return bands.some((gain) => gain !== 0) ? "Custom" : "Flat";
}

function storedSleepUntil(value, now = Date.now()) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= now) {
    return 0;
  }
  return n;
}

function storedSleepMinutes(value, until = 0) {
  if (!until) {
    return 0;
  }
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) {
    return 0;
  }
  return Math.min(240, Math.max(1, Math.round(n)));
}

function storedPosition(value, durationSecs = 0) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) {
    return 0;
  }
  const dur = Number(durationSecs) || 0;
  if (dur > 0 && n >= Math.max(0, dur - 1)) {
    return 0;
  }
  return n;
}

function storedTrack(track) {
  const id = String(track?.id || "").trim();
  if (!id) {
    return null;
  }
  return {
    id,
    title: String(track.title || id),
    artist: String(track.artist || ""),
    album: String(track.album || ""),
    duration_secs: Number(track.duration_secs) || 0,
  };
}

export function serializeSession(state = {}) {
  const tracks = (state.tracks || state.queue || []).map(storedTrack).filter(Boolean);
  let index = Number.isInteger(state.index) ? state.index : -1;
  if (!tracks.length) {
    index = -1;
  } else if (index < 0) {
    index = 0;
  } else if (index >= tracks.length) {
    index = tracks.length - 1;
  }
  const repeat = ["off", "all", "one"].includes(state.repeat) ? state.repeat : "off";
  const eq_bands = storedBands(state.eq_bands);
  const current = index >= 0 ? tracks[index] : null;
  return {
    version: SESSION_VERSION,
    index,
    shuffle: Boolean(state.shuffle),
    repeat,
    automix: Boolean(state.automix),
    volume: storedVolume(state.volume),
    eq_preset: storedPreset(state.eq_preset, eq_bands),
    eq_bands,
    position: storedPosition(state.position, current?.duration_secs),
    sleep_until: storedSleepUntil(state.sleep_until ?? state.sleepUntil),
    sleep_minutes: storedSleepMinutes(
      state.sleep_minutes ?? state.sleepMinutes,
      storedSleepUntil(state.sleep_until ?? state.sleepUntil),
    ),
    tracks,
  };
}

export function parseSession(raw) {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  return serializeSession(raw);
}

export function readSession(filePath) {
  try {
    const text = fs.readFileSync(filePath, "utf8");
    return parseSession(JSON.parse(text));
  } catch {
    return null;
  }
}

export function writeSession(filePath, state) {
  const payload = serializeSession(state);
  fs.mkdirSync(path.dirname(filePath), { recursive: true, mode: 0o700 });
  const tmp = `${filePath}.tmp`;
  fs.writeFileSync(tmp, `${JSON.stringify(payload)}\n`, { mode: 0o600 });
  fs.renameSync(tmp, filePath);
  try {
    fs.chmodSync(filePath, 0o600);
  } catch {
    /* umask may already be correct */
  }
  return payload;
}

export function createSessionStore(filePath, { delayMs = 150 } = {}) {
  let timer = null;
  let pending = null;
  return {
    save(state) {
      pending = state;
      if (timer) {
        clearTimeout(timer);
      }
      timer = setTimeout(() => {
        timer = null;
        if (pending) {
          try {
            writeSession(filePath, pending);
            pending = null;
          } catch {
            /* keep pending for the next save */
          }
        }
      }, delayMs);
      timer.unref?.();
    },
    flush() {
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      if (pending) {
        try {
          writeSession(filePath, pending);
          pending = null;
        } catch {
          /* disk busy */
        }
      }
    },
    load() {
      return readSession(filePath);
    },
  };
}
