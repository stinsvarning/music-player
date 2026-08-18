import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import { setTimeout as delay } from "node:timers/promises";

export class Mpv {
  constructor(socketPath) {
    this.socketPath = socketPath;
    this.proc = null;
    this.requestId = 1;
    this._listeners = new Set();
    this._eventSock = null;
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
        `--input-ipc-server=${this.socketPath}`,
      ],
      { stdio: ["ignore", "ignore", "pipe"] },
    );
    this.proc.stderr?.resume();
    const deadline = Date.now() + 4000;
    while (Date.now() < deadline) {
      if (fs.existsSync(this.socketPath)) {
        this.#listenEvents();
        return;
      }
      if (this.proc.exitCode != null) {
        throw new Error(`mpv exited ${this.proc.exitCode}`);
      }
      await delay(30);
    }
    throw new Error("mpv ipc socket did not appear");
  }

  async command(args) {
    const id = this.requestId++;
    const payload = `${JSON.stringify({ command: args, request_id: id })}\n`;
    const sock = await this.#connect();
    return await new Promise((resolve, reject) => {
      let buf = "";
      const onData = (chunk) => {
        buf += chunk.toString();
        const lines = buf.split("\n");
        buf = lines.pop() || "";
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
          if (msg.request_id === id) {
            cleanup();
            if (msg.error && msg.error !== "success") {
              reject(new Error(msg.error));
            } else {
              resolve(msg.data);
            }
            return;
          }
        }
      };
      const cleanup = () => {
        sock.off("data", onData);
        sock.destroy();
      };
      sock.on("data", onData);
      sock.on("error", (err) => {
        cleanup();
        reject(err);
      });
      sock.write(payload);
      setTimeout(() => {
        cleanup();
        reject(new Error("mpv command timeout"));
      }, 4000);
    });
  }

  async load(url) {
    await this.command(["loadfile", url, "replace"]);
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
    if (this.proc && this.proc.exitCode == null) {
      this.proc.kill("SIGTERM");
      await delay(200);
      if (this.proc.exitCode == null) {
        this.proc.kill("SIGKILL");
      }
    }
    this.proc = null;
    if (this._eventSock) {
      this._eventSock.destroy();
      this._eventSock = null;
    }
    try {
      fs.unlinkSync(this.socketPath);
    } catch {
      /* ignore */
    }
  }

  get pid() {
    return this.proc?.pid ?? null;
  }

  #listenEvents() {
    if (this._eventSock) {
      return;
    }
    const sock = net.connect(this.socketPath);
    this._eventSock = sock;
    let buf = "";
    sock.on("data", (chunk) => {
      buf += chunk.toString();
      const lines = buf.split("\n");
      buf = lines.pop() || "";
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
        if (!msg?.event) {
          continue;
        }
        for (const fn of this._listeners) {
          try {
            fn(msg);
          } catch {
            /* listener errors must not kill the socket */
          }
        }
      }
    });
    sock.on("error", () => {});
  }

  #connect() {
    return new Promise((resolve, reject) => {
      const sock = net.connect(this.socketPath);
      sock.once("connect", () => resolve(sock));
      sock.once("error", reject);
    });
  }
}
