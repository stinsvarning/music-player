import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import { setTimeout as delay } from "node:timers/promises";

export class Mpv {
  constructor(socketPath) {
    this.socketPath = socketPath;
    this.proc = null;
    this.requestId = 1;
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
        `--input-ipc-server=${this.socketPath}`,
      ],
      { stdio: ["ignore", "ignore", "pipe"] },
    );
    this.proc.stderr?.resume();
    const deadline = Date.now() + 4000;
    while (Date.now() < deadline) {
      if (fs.existsSync(this.socketPath)) {
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
    await this.command(["seek", Number(seconds), "absolute"]);
  }

  async setVolume(volume) {
    await this.command(["set_property", "volume", Number(volume)]);
  }

  async setAf(filter) {
    await this.command(["set_property", "af", filter]);
  }

  async get(prop) {
    for (let i = 0; i < 20; i++) {
      try {
        return await this.command(["get_property", prop]);
      } catch (err) {
        if (!String(err.message).includes("unavailable")) {
          throw err;
        }
        await delay(80);
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
    try {
      fs.unlinkSync(this.socketPath);
    } catch {
      /* ignore */
    }
  }

  get pid() {
    return this.proc?.pid ?? null;
  }

  #connect() {
    return new Promise((resolve, reject) => {
      const sock = net.connect(this.socketPath);
      sock.once("connect", () => resolve(sock));
      sock.once("error", reject);
    });
  }
}
