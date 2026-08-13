import fs from "node:fs";
import { readCookieHeader } from "./cookies.js";
import { Mpv } from "./mpv.js";
import { ensureConfigDir, engineSocket, mpvSocket, readCookiesFromSetting } from "./paths.js";
import { Player } from "./player.js";
import { dispatch, listen } from "./server.js";
import { Youtube } from "./youtube.js";

ensureConfigDir();
fs.writeFileSync(`${engineSocket()}.pid`, String(process.pid));

const youtube = new Youtube();
const mpv = new Mpv(mpvSocket());
const player = new Player({ mpv, youtube });

let server;

async function main() {
  const cookiesFrom = readCookiesFromSetting();
  const cookieHeader = readCookieHeader(cookiesFrom);
  await youtube.connect(cookieHeader);
  await mpv.start();
  await player.applyEq();
  server = listen(engineSocket(), async (req) => {
    if (req.cmd === "shutdown") {
      setTimeout(() => shutdown(), 50);
      return { ok: true, shutdown: true };
    }
    return dispatch(player, youtube, req);
  });
  console.error(`music-player engine ready (${engineSocket()})`);
}

async function shutdown() {
  try {
    await mpv.quit();
  } catch {
    /* ignore */
  }
  if (server) {
    server.close();
  }
  try {
    fs.unlinkSync(engineSocket());
  } catch {
    /* ignore */
  }
  try {
    fs.unlinkSync(`${engineSocket()}.pid`);
  } catch {
    /* ignore */
  }
  process.exit(0);
}

process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);

main().catch((err) => {
  console.error(err.message || err);
  process.exit(1);
});
