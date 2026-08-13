import fs from "node:fs";
import net from "node:net";
import { encode, fail, ok, parseRequest } from "./protocol.js";

export function listen(socketPath, handler) {
  try {
    fs.unlinkSync(socketPath);
  } catch {
    /* missing is fine */
  }
  const server = net.createServer((sock) => {
    let buf = "";
    sock.on("data", async (chunk) => {
      buf += chunk.toString();
      while (buf.includes("\n")) {
        const idx = buf.indexOf("\n");
        const line = buf.slice(0, idx);
        buf = buf.slice(idx + 1);
        const parsed = parseRequest(line);
        let resp;
        try {
          resp = parsed.ok ? await handler(parsed.request) : fail(parsed.error);
        } catch (err) {
          resp = fail(err.message || err);
        }
        sock.write(encode(resp));
      }
    });
  });
  server.listen(socketPath);
  fs.chmodSync(socketPath, 0o600);
  return server;
}

export async function dispatch(player, youtube, req) {
  switch (req.cmd) {
    case "status":
      return ok(await player.status());
    case "play":
      await player.play();
      return ok();
    case "pause":
      await player.pause();
      return ok();
    case "toggle":
      await player.toggle();
      return ok();
    case "stop":
      await player.stop();
      return ok();
    case "next":
      await player.next();
      return ok();
    case "prev":
      await player.prev();
      return ok();
    case "seek":
      await player.seek(req.value);
      return ok();
    case "volume":
      await player.volume(req.value);
      return ok();
    case "shuffle":
      player.setShuffle(req.name || "toggle");
      return ok({ shuffle: player.shuffle });
    case "repeat":
      player.setRepeat(req.name || "cycle");
      return ok({ repeat: player.repeat });
    case "eq":
      if (req.band != null && req.band >= 0) {
        await player.setEqBand(req.band, req.value);
      } else {
        await player.setEqPreset(req.name);
      }
      return ok({ eq_preset: player.eqPreset, eq_bands: player.eqBands });
    case "queue.list":
      return ok({ tracks: player.queue, index: player.index, total: player.queue.length });
    case "queue.play":
      await player.playIndex(req.index);
      return ok();
    case "track.play":
      await player.playTrack(req.track, { replaceQueue: false });
      return ok();
    case "track.queue":
      player.queueTrack(req.track);
      return ok();
    case "search":
      return ok({ tracks: await youtube.search(req.query, req.limit || 20) });
    case "playlists":
      return ok({ playlists: await youtube.playlists() });
    case "playlist.tracks": {
      const tracks = await youtube.playlistTracks(req.id);
      if (req.load) {
        player.replaceQueue(tracks, 0);
        if (tracks.length) {
          await player.playIndex(0);
        }
      }
      return ok({ tracks, total: tracks.length });
    }
    case "playlist.play": {
      const tracks = await youtube.playlistTracks(req.id);
      player.replaceQueue(tracks, req.index || 0);
      if (tracks.length) {
        await player.playIndex(player.index);
      }
      return ok({ total: tracks.length });
    }
    case "shutdown":
      return ok({ shutdown: true });
    default:
      return fail(`unknown command: ${req.cmd}`);
  }
}
