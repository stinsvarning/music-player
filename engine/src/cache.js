import fs from "node:fs";
import path from "node:path";

const DEFAULT_TTL_MS = 5 * 60 * 60 * 1000;

export function parseExpireAt(url) {
  try {
    const parsed = new URL(url);
    const raw = parsed.searchParams.get("expire") || parsed.searchParams.get("expires") || parsed.searchParams.get("exp");
    if (!raw) {
      return null;
    }
    const n = Number(raw);
    if (!Number.isFinite(n) || n <= 0) {
      return null;
    }
    return n < 1e12 ? n * 1000 : n;
  } catch {
    return null;
  }
}

export class UrlCache {
  constructor(ttlMs = DEFAULT_TTL_MS, now = () => Date.now(), filePath = "") {
    if (ttlMs && typeof ttlMs === "object") {
      const opts = ttlMs;
      ttlMs = opts.ttlMs ?? DEFAULT_TTL_MS;
      now = opts.now ?? (() => Date.now());
      filePath = opts.filePath ?? "";
    }
    this.ttlMs = ttlMs;
    this.now = now;
    this.filePath = filePath || "";
    this.map = new Map();
    this._timer = null;
    this._dirty = false;
    this.#load();
  }

  get(videoId) {
    const row = this.map.get(videoId);
    if (!row) {
      return null;
    }
    if (this.now() >= row.expiresAt) {
      this.map.delete(videoId);
      this.#scheduleSave();
      return null;
    }
    return row.url;
  }

  set(videoId, url) {
    const id = String(videoId || "").trim();
    if (!id || !url) {
      return;
    }
    const fromUrl = parseExpireAt(url);
    const expiresAt = fromUrl || this.now() + this.ttlMs;
    if (expiresAt <= this.now()) {
      this.map.delete(id);
      this.#scheduleSave();
      return;
    }
    this.map.set(id, { url: String(url), expiresAt });
    this.#scheduleSave();
  }

  drop(videoId) {
    if (this.map.delete(videoId)) {
      this.#scheduleSave();
    }
  }

  flush() {
    if (this._timer) {
      clearTimeout(this._timer);
      this._timer = null;
    }
    if (this._dirty) {
      this.#write();
    }
  }

  #load() {
    if (!this.filePath) {
      return;
    }
    try {
      const raw = JSON.parse(fs.readFileSync(this.filePath, "utf8"));
      const entries = raw?.entries && typeof raw.entries === "object" ? raw.entries : raw;
      if (!entries || typeof entries !== "object") {
        return;
      }
      const now = this.now();
      for (const [id, row] of Object.entries(entries)) {
        if (!id || !row?.url || !Number.isFinite(row.expiresAt) || row.expiresAt <= now) {
          continue;
        }
        this.map.set(id, { url: String(row.url), expiresAt: row.expiresAt });
      }
    } catch {
      /* missing or corrupt */
    }
  }

  #scheduleSave() {
    if (!this.filePath) {
      return;
    }
    this._dirty = true;
    if (this._timer) {
      return;
    }
    this._timer = setTimeout(() => {
      this._timer = null;
      this.#write();
    }, 150);
    this._timer.unref?.();
  }

  #write() {
    if (!this.filePath) {
      this._dirty = false;
      return;
    }
    const now = this.now();
    const entries = {};
    for (const [id, row] of this.map) {
      if (!row?.url || row.expiresAt <= now) {
        this.map.delete(id);
        continue;
      }
      entries[id] = { url: row.url, expiresAt: row.expiresAt };
    }
    const payload = `${JSON.stringify({ version: 1, entries })}\n`;
    try {
      fs.mkdirSync(path.dirname(this.filePath), { recursive: true, mode: 0o700 });
      const tmp = `${this.filePath}.tmp`;
      fs.writeFileSync(tmp, payload, { mode: 0o600 });
      fs.renameSync(tmp, this.filePath);
      try {
        fs.chmodSync(this.filePath, 0o600);
      } catch {
        /* umask may already be correct */
      }
      this._dirty = false;
    } catch {
      /* keep dirty for the next flush */
    }
  }
}
