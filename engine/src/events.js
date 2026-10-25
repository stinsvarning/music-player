import { encode } from "./protocol.js";

// Pushes status to subscribed IPC clients whenever the player reports a change,
// so the UI does not have to poll. Changes are coalesced (debounceMs) and an
// identical snapshot is never sent twice. While playing, a slow heartbeat keeps
// position in sync and lets status() expire the sleep timer.
export class StatusHub {
  constructor(player, { debounceMs = 30, heartbeatMs = 2000 } = {}) {
    this.player = player;
    this.debounceMs = debounceMs;
    this.heartbeatMs = heartbeatMs;
    this.clients = new Set();
    this._timer = null;
    this._busy = false;
    this._again = false;
    this._last = "";
    this._lastPos = null; // { pos, at, playing }
    this._beat = null;
    this._off = typeof player?.onChange === "function" ? player.onChange(() => this.schedule()) : null;
  }

  get size() {
    return this.clients.size;
  }

  async add(sock) {
    this.clients.add(sock);
    const drop = () => this.remove(sock);
    sock.once("close", drop);
    sock.once("error", drop);
    const st = await this.player.status();
    this._last = signature(st);
    this.#notePosition(st);
    this.#syncHeartbeat(st);
    return st;
  }

  remove(sock) {
    this.clients.delete(sock);
    if (!this.clients.size) {
      this.#stopHeartbeat();
    }
  }

  schedule() {
    if (!this.clients.size) {
      return;
    }
    if (this._busy) {
      this._again = true;
      return;
    }
    if (this._timer) {
      return;
    }
    this._timer = setTimeout(() => {
      this._timer = null;
      this.publish().catch(() => {});
    }, this.debounceMs);
    this._timer.unref?.();
  }

  async publish({ force = false } = {}) {
    if (!this.clients.size) {
      return false;
    }
    this._busy = true;
    let sent = false;
    try {
      const st = await this.player.status();
      this.#syncHeartbeat(st);
      const sig = signature(st);
      if (force || sig !== this._last || this.#jumped(st)) {
        this._last = sig;
        this.#notePosition(st);
        const line = encode({ ok: true, event: "status", ...st });
        for (const sock of this.clients) {
          if (sock.destroyed || !sock.writable) {
            this.clients.delete(sock);
            continue;
          }
          sock.write(line);
        }
        sent = true;
      }
    } finally {
      this._busy = false;
    }
    if (this._again) {
      this._again = false;
      this.schedule();
    }
    return sent;
  }

  close() {
    this._off?.();
    this.#stopHeartbeat();
    if (this._timer) {
      clearTimeout(this._timer);
      this._timer = null;
    }
    this.clients.clear();
  }

  // A seek is a position change the client cannot predict.
  #jumped(st) {
    const prev = this._lastPos;
    if (!prev) {
      return true;
    }
    const expect = prev.pos + (prev.playing ? (Date.now() - prev.at) / 1000 : 0);
    return Math.abs(Number(st?.position || 0) - expect) > 1.5;
  }

  #notePosition(st) {
    this._lastPos = { pos: Number(st?.position || 0), at: Date.now(), playing: st?.state === "playing" };
  }

  #syncHeartbeat(st) {
    if (st?.state === "playing" && this.clients.size) {
      if (!this._beat) {
        this._beat = setInterval(() => this.publish({ force: true }).catch(() => {}), this.heartbeatMs);
        this._beat.unref?.();
      }
    } else {
      this.#stopHeartbeat();
    }
  }

  #stopHeartbeat() {
    if (this._beat) {
      clearInterval(this._beat);
      this._beat = null;
    }
  }
}

// Everything but the live position: a position-only change is not news.
function signature(st) {
  const { position, ...rest } = st || {};
  return JSON.stringify(rest);
}
