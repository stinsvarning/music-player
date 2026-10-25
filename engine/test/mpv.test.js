import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { setTimeout as delay } from "node:timers/promises";
import { lavfiEqualizer, parseAmetadataLog, spectrumBandFile, VIS_BANDS_HZ } from "../src/eq.js";
import { Mpv } from "../src/mpv.js";

test("mpv plays a local file and seeks absolutely", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "mpv-test-"));
  const wav = path.join(dir, "silence.wav");
  const sock = path.join(dir, "mpv.sock");
  const made = spawnSync(
    "ffmpeg",
    ["-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "5", wav],
    { encoding: "utf8" },
  );
  assert.equal(made.status, 0, made.stderr);
  const mpv = new Mpv(sock, { extraArgs: ["--ao=null"] }); // tests never make sound
  await mpv.start();
  try {
    await mpv.load(wav);
    await delay(300);
    const paused = await mpv.get("pause");
    if (paused) {
      await mpv.pause(false);
      await delay(200);
    }
    await mpv.seekAbsolute(2);
    await delay(150);
    const pos = await mpv.get("time-pos");
    assert.ok(pos >= 1.7 && pos <= 3.0, `expected ~2s, got ${pos}`);
  } finally {
    await mpv.quit();
  }
});

test("the spectrum taps run in mpv and write per-band RMS", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "mpv-test-"));
  const wav = path.join(dir, "tone.wav");
  const spec = path.join(dir, "spectrum");
  fs.mkdirSync(spec);
  const made = spawnSync(
    "ffmpeg",
    ["-y", "-f", "lavfi", "-i", "sine=f=1000:r=48000", "-ac", "2", "-t", "4", wav],
    { encoding: "utf8" },
  );
  assert.equal(made.status, 0, made.stderr);
  const mpv = new Mpv(path.join(dir, "mpv.sock"), { extraArgs: ["--ao=null"] }); // tests never make sound
  await mpv.start();
  try {
    await mpv.setAf(lavfiEqualizer([0, 0, 0, 0, 0, 0, 0, 0, 0, 0], spec));
    await mpv.load(wav);
    await delay(300);
    if (await mpv.get("pause")) {
      await mpv.pause(false);
    }
    await delay(1500);
    const rms = VIS_BANDS_HZ.map((_, i) => {
      const text = fs.readFileSync(spectrumBandFile(spec, i), "utf8");
      return Number(parseAmetadataLog(text)["lavfi.astats.Overall.RMS_level"]);
    });
    // a 1 kHz tone: loudest in the band around 1 kHz, far quieter at the edges
    const loudest = rms.indexOf(Math.max(...rms));
    assert.equal(VIS_BANDS_HZ[loudest], 1116, rms.join(" "));
    assert.ok(rms[0] < rms[loudest] - 20 && rms[9] < rms[loudest] - 20, rms.join(" "));
    const frames = fs.readFileSync(spectrumBandFile(spec, 5), "utf8").split("\n").filter((l) => l.startsWith("frame:"));
    assert.ok(frames.length >= 3, `few measured frames: ${frames.length}`);
  } finally {
    await mpv.quit();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("turning the spectrum taps off and on mid-track drops no audio", async () => {
  // mpv swaps the lavfi graph in place; the pcm output must stay one unbroken sine.
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "mpv-test-"));
  const wav = path.join(dir, "tone.wav");
  const out = path.join(dir, "out.wav");
  const spec = path.join(dir, "spectrum");
  fs.mkdirSync(spec);
  const made = spawnSync("ffmpeg", ["-y", "-f", "lavfi", "-i", "sine=f=1000:r=48000", "-ac", "2", "-t", "2", wav], { encoding: "utf8" });
  assert.equal(made.status, 0, made.stderr);
  // a file instead of a sound card; arealtime keeps it at playback speed so the toggles land mid-track
  const mpv = new Mpv(path.join(dir, "mpv.sock"), { extraArgs: ["--ao=pcm", `--ao-pcm-file=${out}`] });
  const flat = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
  const pace = ",lavfi=[arealtime]";
  await mpv.start();
  try {
    await mpv.setAf(lavfiEqualizer(flat, spec) + pace);
    await mpv.load(wav);
    await delay(200);
    if (await mpv.get("pause")) {
      await mpv.pause(false);
    }
    for (let i = 0; i < 12; i += 1) {
      await delay(120);
      await mpv.setAf(lavfiEqualizer(flat, i % 2 ? spec : "") + pace);
    }
    for (let i = 0; i < 40 && !(await mpv.get("idle-active")); i += 1) {
      await delay(100);
    }
  } finally {
    await mpv.quit();
  }
  try {
    const buf = fs.readFileSync(out);
    const at = buf.indexOf("data") + 8;
    const left = [];
    for (let o = at; o + 4 <= buf.length; o += 4) {
      left.push(buf.readInt16LE(o) / 32768);
    }
    assert.ok(Math.abs(left.length - 96000) < 1200, `samples ${left.length}`);
    // a pure sine obeys x[n] = 2cos(w) x[n-1] - x[n-2]; a dropped or doubled block breaks it
    const k = 2 * Math.cos((2 * Math.PI * 1000) / 48000);
    let breaks = 0;
    for (let n = 2; n < left.length; n += 1) {
      if (Math.abs(left[n] - (k * left[n - 1] - left[n - 2])) > 0.002) {
        breaks += 1;
      }
    }
    assert.equal(breaks, 0);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("observed properties arrive as property-change events", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "mpv-test-"));
  const sock = path.join(dir, "mpv.sock");
  const mpv = new Mpv(sock, { extraArgs: ["--ao=null"] });
  await mpv.start();
  const seen = [];
  mpv.onEvent((ev) => {
    if (ev.event === "property-change") {
      seen.push(`${ev.name}=${JSON.stringify(ev.data)}`);
    }
  });
  try {
    mpv.observe(["pause", "volume"]);
    await delay(150);
    await mpv.setVolume(33);
    await mpv.pause(true);
    await delay(200);
    assert.ok(seen.includes("volume=33"), seen.join(" "));
    assert.ok(seen.includes("pause=true"), seen.join(" "));
  } finally {
    await mpv.quit();
  }
});

function fakeMpvServer(sockPath, { onCommand } = {}) {
  const conns = new Set();
  const server = net.createServer((conn) => {
    conns.add(conn);
    conn.on("close", () => conns.delete(conn));
    let buf = "";
    conn.on("data", (chunk) => {
      buf += chunk.toString();
      while (buf.includes("\n")) {
        const i = buf.indexOf("\n");
        const msg = JSON.parse(buf.slice(0, i));
        buf = buf.slice(i + 1);
        const reply = onCommand ? onCommand(msg, conn) : { data: null };
        if (reply && msg.request_id != null) {
          conn.write(`${JSON.stringify({ request_id: msg.request_id, error: "success", ...reply })}\n`);
        }
      }
    });
  });
  return new Promise((resolve) => server.listen(sockPath, () => resolve({ server, conns })));
}

test("commands share one connection and replies match by request_id", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "mpv-fake-"));
  const sockPath = path.join(dir, "mpv.sock");
  let accepted = 0;
  const { server } = await fakeMpvServer(sockPath, {
    onCommand: (msg) => {
      if (msg.command[0] === "get_property") {
        return { data: `v:${msg.command[1]}` };
      }
      return { data: null };
    },
  });
  server.on("connection", () => {
    accepted += 1;
  });
  const mpv = new Mpv(sockPath);
  await mpv.attach();
  const got = await Promise.all(["a", "b", "c", "d"].map((p) => mpv.get(p)));
  assert.deepEqual(got, ["v:a", "v:b", "v:c", "v:d"]);
  for (let i = 0; i < 20; i += 1) {
    await mpv.get("x");
  }
  assert.equal(accepted, 1);
  assert.equal(mpv.connects, 1);
  await mpv.quit();
  await new Promise((r) => server.close(r));
});

test("a dropped connection fails in-flight commands, reconnects, and re-observes", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "mpv-fake-"));
  const sockPath = path.join(dir, "mpv.sock");
  const observes = [];
  const { server, conns } = await fakeMpvServer(sockPath, {
    onCommand: (msg) => {
      if (msg.command[0] === "observe_property") {
        observes.push(msg.command[2]);
        return null;
      }
      if (msg.command[0] === "get_property" && msg.command[1] === "hang") {
        return null; // never answer
      }
      return { data: 7 };
    },
  });
  const mpv = new Mpv(sockPath, { timeoutMs: 2000 });
  const events = [];
  mpv.onEvent((ev) => events.push(ev.event));
  await mpv.attach();
  mpv.observe(["pause"]);
  await delay(30);
  const hanging = mpv.get("hang");
  await delay(30);
  for (const c of conns) c.destroy();
  await assert.rejects(hanging, /closed/);
  await delay(400); // background reconnect
  assert.equal(mpv.connects, 2);
  assert.deepEqual(observes, ["pause", "pause"]);
  for (const c of conns) c.write('{"event":"property-change","name":"pause","data":true}\n');
  await delay(30);
  assert.deepEqual(events, ["property-change"]);
  assert.equal(await mpv.get("volume"), 7);
  await mpv.quit();
  await new Promise((r) => server.close(r));
});

test("errors and timeouts reject only their own command", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "mpv-fake-"));
  const sockPath = path.join(dir, "mpv.sock");
  const { server } = await fakeMpvServer(sockPath, {
    onCommand: (msg) => {
      if (msg.command[1] === "missing") return { error: "property unavailable" };
      if (msg.command[1] === "slow") return null;
      return { data: 1 };
    },
  });
  const mpv = new Mpv(sockPath, { timeoutMs: 150 });
  await mpv.attach();
  await assert.rejects(mpv.command(["get_property", "missing"]), /unavailable/);
  assert.equal(await mpv.get("missing"), null);
  await assert.rejects(mpv.command(["get_property", "slow"]), /timeout/);
  assert.equal(await mpv.get("ok"), 1);
  assert.equal(mpv.connects, 1);
  await mpv.quit();
  await new Promise((r) => server.close(r));
});
