import { execFileSync } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import { encode } from "./protocol.js";

export function pidAlive(pid) {
  const n = Number(pid);
  if (!Number.isInteger(n) || n <= 0) {
    return false;
  }
  try {
    process.kill(n, 0);
    return true;
  } catch {
    return false;
  }
}

export function acquireLock(lockPath) {
  for (let i = 0; i < 2; i += 1) {
    try {
      const fd = fs.openSync(lockPath, "wx");
      fs.writeFileSync(fd, `${process.pid}\n`);
      return { fd, path: lockPath };
    } catch (err) {
      if (err.code !== "EEXIST") {
        throw err;
      }
      let owner = 0;
      try {
        owner = Number.parseInt(fs.readFileSync(lockPath, "utf8").trim(), 10);
      } catch {
        owner = 0;
      }
      if (pidAlive(owner)) {
        return null;
      }
      try {
        fs.unlinkSync(lockPath);
      } catch {
        /* raced */
      }
    }
  }
  return null;
}

export function releaseLock(lock) {
  if (!lock) {
    return;
  }
  try {
    fs.closeSync(lock.fd);
  } catch {
    /* already closed */
  }
  try {
    fs.unlinkSync(lock.path);
  } catch {
    /* missing is fine */
  }
}

export function pingEngine(socketPath, timeoutMs = 400) {
  return new Promise((resolve) => {
    if (!socketPath || !fs.existsSync(socketPath)) {
      resolve(false);
      return;
    }
    const sock = net.connect(socketPath);
    let done = false;
    const finish = (value) => {
      if (done) {
        return;
      }
      done = true;
      sock.destroy();
      resolve(value);
    };
    sock.setTimeout(timeoutMs);
    sock.on("connect", () => {
      sock.write(encode({ cmd: "status" }));
    });
    sock.on("data", (chunk) => {
      try {
        const msg = JSON.parse(String(chunk).split("\n")[0] || "{}");
        finish(msg.ok === true);
      } catch {
        finish(false);
      }
    });
    sock.on("timeout", () => finish(false));
    sock.on("error", () => finish(false));
  });
}

export function killOrphanMpv(socketPath) {
  if (!socketPath) {
    return;
  }
  try {
    execFileSync("pkill", ["-f", `input-ipc-server=${socketPath}`], { stdio: "ignore" });
  } catch {
    /* no matches */
  }
}
