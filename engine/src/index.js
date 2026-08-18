import fs from "node:fs";
import { setTimeout as delay } from "node:timers/promises";
import { LOGIN_REQUIRED, clearSavedHeader, clearSignedOut, isSignedOut, markSignedOut, resolveCookies, writeSavedHeader } from "./cookies.js";
import { Mpv } from "./mpv.js";
import { UrlCache } from "./cache.js";
import { listenHttp, loadOrCreateToken } from "./http.js";
import {
  ensureConfigDir,
  engineLockPath,
  engineSocket,
  httpAllowDangerous,
  httpEnabled,
  httpPort,
  httpTokenPath,
  mpvSocket,
  readCookiesFromSetting,
  savedCookiesPath,
  signedOutPath,
  urlCachePath,
} from "./paths.js";
import { Player } from "./player.js";
import { createSessionStore, sessionPath } from "./session.js";
import { startMpris } from "./mpris.js";
import { dispatch, listen } from "./server.js";
import { ok } from "./protocol.js";
import { acquireLock, killOrphanMpv, pingEngine, releaseLock } from "./singleton.js";
import { Youtube } from "./youtube.js";

ensureConfigDir();

const youtube = new Youtube();
const mpv = new Mpv(mpvSocket());
const sessionStore = createSessionStore(sessionPath());
const player = new Player({
  mpv,
  youtube,
  persist: sessionStore,
  cache: new UrlCache({ filePath: urlCachePath() }),
});
player.restoreSession(sessionStore.load());

let server;
let httpServer;

function authSnapshot() {
  return {
    logged_in: Boolean(youtube.loggedIn),
    source: youtube.authSource || "",
    error: youtube.authError || "",
  };
}

async function refreshAuth({ skipSaved = false, force = false } = {}) {
  if (force) {
    clearSignedOut(signedOutPath());
  } else if (isSignedOut(signedOutPath())) {
    youtube.disconnect();
    youtube.authError = "";
    return { ...authSnapshot(), signed_out: true };
  }
  const resolved = resolveCookies({
    spec: readCookiesFromSetting(),
    savedPath: savedCookiesPath(),
    skipSaved,
  });
  if (!resolved.header) {
    youtube.disconnect();
    youtube.authError = LOGIN_REQUIRED;
    return { ...authSnapshot(), error: LOGIN_REQUIRED };
  }
  try {
    await youtube.connect(resolved.header);
    youtube.authSource = resolved.source;
    writeSavedHeader(savedCookiesPath(), resolved.header);
    return authSnapshot();
  } catch (err) {
    youtube.disconnect();
    youtube.authError = err.message || LOGIN_REQUIRED;
    return authSnapshot();
  }
}

async function waitForExistingEngine() {
  for (let i = 0; i < 80; i += 1) {
    if (await pingEngine(engineSocket())) {
      return true;
    }
    await delay(100);
  }
  return false;
}

async function main() {
  if (await pingEngine(engineSocket())) {
    console.error("engine already running");
    process.exit(0);
  }
  const lock = acquireLock(engineLockPath());
  if (!lock) {
    if (await waitForExistingEngine()) {
      process.exit(0);
    }
    throw new Error("engine lock is busy");
  }
  process.on("exit", () => releaseLock(lock));
  if (await pingEngine(engineSocket())) {
    releaseLock(lock);
    process.exit(0);
  }
  fs.writeFileSync(`${engineSocket()}.pid`, String(process.pid));
  killOrphanMpv(mpvSocket());
  await refreshAuth();
  await mpv.start();
  await player.applyEq();
  await player.applyVolume();
  try {
    const handle = async (req) => {
      if (req.cmd === "shutdown") {
        setTimeout(() => shutdown(), 50);
        return { ok: true, shutdown: true };
      }
      if (req.cmd === "auth.status") {
        return ok(authSnapshot());
      }
      if (req.cmd === "auth.refresh") {
        return ok(
          await refreshAuth({
            skipSaved: Boolean(req.skip_saved),
            force: Boolean(req.force),
          }),
        );
      }
      if (req.cmd === "auth.logout") {
        clearSavedHeader(savedCookiesPath());
        markSignedOut(signedOutPath());
        youtube.disconnect();
        youtube.authError = "";
        return ok({ ...authSnapshot(), signed_out: true });
      }
      return dispatch(player, youtube, req);
    };
    server = await listen(engineSocket(), handle);
    if (httpEnabled()) {
      try {
        const token = loadOrCreateToken(httpTokenPath());
        httpServer = await listenHttp({
          host: "127.0.0.1",
          port: httpPort(),
          token,
          handler: handle,
          allowDangerous: httpAllowDangerous(),
        });
        console.error(`music-player http ready (127.0.0.1:${httpPort()})`);
      } catch (err) {
        console.error("http skipped:", err.message || err);
      }
    }
  } catch (err) {
    if (String(err.message || err).includes("already listening")) {
      console.error("engine already running");
      releaseLock(lock);
      process.exit(0);
    }
    throw err;
  }
  try {
    await startMpris(player, { onQuit: () => shutdown() });
    console.error("mpris ready (org.mpris.MediaPlayer2.Music)");
  } catch (err) {
    console.error("mpris skipped:", err.message || err);
  }
  console.error(`music-player engine ready (${engineSocket()})`);
}

async function shutdown() {
  try {
    await player.flushSession();
  } catch {
    /* ignore */
  }
  try {
    await mpv.quit();
  } catch {
    /* ignore */
  }
  if (server) {
    server.close();
  }
  if (httpServer) {
    httpServer.close();
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
  try {
    killOrphanMpv(mpvSocket());
  } catch {
    /* ignore */
  }
  process.exit(0);
}

process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
process.on("uncaughtException", (err) => {
  console.error("uncaughtException:", err?.message || err);
  try {
    killOrphanMpv(mpvSocket());
  } catch {
    /* ignore */
  }
  process.exit(1);
});
process.on("unhandledRejection", (err) => {
  console.error("unhandledRejection:", err?.message || err);
  try {
    killOrphanMpv(mpvSocket());
  } catch {
    /* ignore */
  }
  process.exit(1);
});

main().catch((err) => {
  console.error(err.message || err);
  process.exit(1);
});
