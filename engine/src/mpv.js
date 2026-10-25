import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import { setTimeout as delay } from "node:timers/promises";

const COMMAND_TIMEOUT_MS = 4000;
const OBSERVE_BASE_ID = 100;

/**
 * mpv over its JSON IPC socket. One long-lived connection carries both commands
 * (matched to replies by request_id) and events. If the connection drops it is
 * re-opened on the next command or after a short backoff, and observed
 * properties are re-registered so property-change events keep flowing.
 */
export class Mpv {
  constructor(socketPath, { extraArgs = [], timeoutMs = COMMAND_TIMEOUT_MS } = {}) {
    this.socketPath = socketPath;
    this.extraArgs = [...extraArgs];
    this.timeoutMs = timeoutMs;
    this.proc = null;
    this.requestId = 1;
    this.connects = 0; // how many times the IPC connection was (re)opened
    this._listeners = new Set();
    this._observed = [];
    this._sock = null;
    this._connecting = null;
    this._pending = new Map();
    this._buf = "";
    this._closing = false;
    this._retry = null;
  }

  /** Ask mpv to report these properties as property-change events. */
  observe(names) {
    const fresh = [];
    for (const name of names || []) {
      if (!this._observed.includes(name)) {
        this._observed.push(name);
        fresh.push(name);
      }
    }
    if (this._sock && !this._sock.destroyed) {
      this.#sendObserves(fresh);
    } else {
      this.#ensure().catch(() => {});
    }
  }

  onEvent(fn) {
    this._listeners.add(fn);
    return () => this._listeners.delete(fn);
  }

  async start() {
    try {
      fs.unlinkSync(this.socketPath);
    } catch {
      /* missing is fine */
    }
    this._closing = false;
    this.proc = spawn(
      "mpv",
      [
        "--idle=yes",
        "--no-video",
        "--force-window=no",
        "--audio-display=no",
        "--no-terminal",
        "--hr-seek=yes",
        "--force-seekable=yes",
        "--load-scripts=no",
        "--prefetch-playlist=yes",
        "--gapless-audio=weak",
        `--input-ipc-server=${this.socketPath}`,
        ...this.extraArgs,
      ],
      { stdio: ["ignore", "ignore", "pipe"] },
    );
    this.proc.stderr?.resume();
    const deadline = Date.now() + 4000;
    while (Date.now() < deadline) {
      if (fs.existsSync(this.socketPath)) {
        try {
          await this.#ensure();
          return;
        } catch {
          /* socket file exists but is not accepting yet */
        }
      }
      if (this.proc.exitCode != null) {
        throw new Error(`mpv exited ${this.proc.exitCode}`);
      }
      await delay(30);
    }
    throw new Error("mpv ipc socket did not appear");
  }

  /** Attach to an mpv that is already listening on socketPath (no spawn). */
  async attach() {
    this._closing = false;
    await this.#ensure();
  }

  async command(args) {
    let sock;
    try {
      sock = await this.#ensure();
    } catch (err) {
      // one quick retry: mpv may be restarting its socket
      await delay(50);
      sock = await this.#ensure().catch(() => {
        throw err;
      });
    }
    const id = this.requestId++;
    return await new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this._pending.delete(id);
        reject(new Error("mpv command timeout"));
      }, this.timeoutMs);
      timer.unref?.();
      this._pending.set(id, { resolve, reject, timer });
      sock.write(`${JSON.stringify({ command: args, request_id: id })}\n`, (err) => {
        if (err && this._pending.has(id)) {
          clearTimeout(timer);
          this._pending.delete(id);
          reject(err);
        }
      });
    });
  }

  async load(url) {
    await this.command(["loadfile", url, "replace"]);
  }

  async append(url) {
    await this.command(["loadfile", url, "append"]);
  }

  async pause(paused) {
    await this.command(["set_property", "pause", paused]);
  }

  async seekAbsolute(seconds) {
    const target = Number(seconds);
    if (!Number.isFinite(target) || target < 0) {
      return;
    }
    try {
      await this.command(["seek", target, "absolute+exact"]);
    } catch {
      await this.command(["set_property", "time-pos", target]);
    }
  }

  async setVolume(volume) {
    await this.command(["set_property", "volume", Number(volume)]);
  }

  async setAf(filter) {
    await this.command(["set_property", "af", filter]);
  }

  async get(prop, retries = 1) {
    for (let i = 0; i < retries; i++) {
      try {
        return await this.command(["get_property", prop]);
      } catch (err) {
        if (!String(err.message).includes("unavailable")) {
          throw err;
        }
        if (i + 1 < retries) {
          await delay(80);
        }
      }
    }
    return null;
  }

  async quit() {
    try {
      await this.command(["quit"]);
    } catch {
      /* socket may close */
    }
    this._closing = true;
    if (this._retry) {
      clearTimeout(this._retry);
      this._retry = null;
    }
    if (this.proc && this.proc.exitCode == null) {
      this.proc.kill("SIGTERM");
      await delay(200);
      if (this.proc.exitCode == null) {
        this.proc.kill("SIGKILL");
      }
    }
    this.proc = null;
    this.#drop(new Error("mpv quit"));
    try {
      fs.unlinkSync(this.socketPath);
    } catch {
      /* ignore */
    }
  }

  get pid() {
    return this.proc?.pid ?? null;
  }

  get connected() {
    return Boolean(this._sock && !this._sock.destroyed);
  }

  #ensure() {
    if (this._sock && !this._sock.destroyed) {
      return Promise.resolve(this._sock);
    }
    if (this._connecting) {
      return this._connecting;
    }
    if (this._closing) {
      return Promise.reject(new Error("mpv is closed"));
    }
    this._connecting = new Promise((resolve, reject) => {
      const sock = net.connect(this.socketPath);
      const fail = (err) => {
        sock.destroy();
        reject(err);
      };
      sock.once("error", fail);
      sock.once("connect", () => {
        sock.off("error", fail);
        this._sock = sock;
        this._buf = "";
        this.connects += 1;
        sock.setNoDelay?.(true);
        sock.on("data", (chunk) => this.#onData(chunk));
        sock.on("error", () => {});
        sock.on("close", () => {
          if (this._sock === sock) {
            this.#drop(new Error("mpv ipc connection closed"));
            this.#scheduleReconnect();
          }
        });
        this.#sendObserves(this._observed);
        resolve(sock);
      });
    }).finally(() => {
      this._connecting = null;
    });
    return this._connecting;
  }

  // Keep events flowing after a drop even when nobody sends a command.
  #scheduleReconnect(wait = 200) {
    if (this._closing || this._retry || (this.proc && this.proc.exitCode != null)) {
      return;
    }
    this._retry = setTimeout(() => {
      this._retry = null;
      this.#ensure().catch(() => this.#scheduleReconnect(Math.min(2000, wait * 2)));
    }, wait);
    this._retry.unref?.();
  }

  #drop(err) {
    const sock = this._sock;
    this._sock = null;
    this._buf = "";
    if (sock && !sock.destroyed) {
      sock.destroy();
    }
    for (const [id, waiter] of this._pending) {
      clearTimeout(waiter.timer);
      waiter.reject(err);
      this._pending.delete(id);
    }
  }

  #sendObserves(names) {
    const sock = this._sock;
    if (!sock || sock.destroyed) {
      return;
    }
    for (const name of names) {
      const i = this._observed.indexOf(name);
      sock.write(`${JSON.stringify({ command: ["observe_property", OBSERVE_BASE_ID + i, name] })}\n`);
    }
  }

  #onData(chunk) {
    this._buf += chunk.toString();
    const lines = this._buf.split("\n");
    this._buf = lines.pop() || "";
    for (const line of lines) {
      if (!line.trim()) {
        continue;
      }
      let msg;
      try {
        msg = JSON.parse(line);
      } catch {
        continue;
      }
      if (msg?.event) {
        for (const fn of this._listeners) {
          try {
            fn(msg);
          } catch {
            /* listener errors must not kill the socket */
          }
        }
        continue;
      }
      const waiter = msg && this._pending.get(msg.request_id);
      if (!waiter) {
        continue; // e.g. the replies to observe_property
      }
      this._pending.delete(msg.request_id);
      clearTimeout(waiter.timer);
      if (msg.error && msg.error !== "success") {
        waiter.reject(new Error(msg.error));
      } else {
        waiter.resolve(msg.data);
      }
    }
  }
}
