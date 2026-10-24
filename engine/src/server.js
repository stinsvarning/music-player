import fs from "node:fs";
import net from "node:net";
import { commandCatalog } from "./commands.js";
import { attachId, encode, fail, ok, parseRequest } from "./protocol.js";
import { isUnplayableError } from "./playable.js";
import { pingEngine } from "./singleton.js";

function videoIdOf(req) {
  return String(req?.id || req?.track?.id || "").trim();
}

function createIpcServer(handler) {
  return net.createServer((sock) => {
    let buf = "";
    let chain = Promise.resolve();
    sock.on("data", (chunk) => {
      buf += chunk.toString();
      while (buf.includes("\n")) {
        const idx = buf.indexOf("\n");
        const line = buf.slice(0, idx);
        buf = buf.slice(idx + 1);
        const parsed = parseRequest(line);
        chain = chain
          .then(async () => {
            let resp;
            try {
              resp = parsed.ok ? await handler(parsed.request) : fail(parsed.error);
            } catch (err) {
              resp = fail(err.message || err);
            }
            if (!sock.destroyed) {
              const req = parsed.ok ? parsed.request : {};
              sock.write(encode(attachId(req, resp)));
            }
          })
          .catch(() => {});
      }
    });
    sock.on("error", () => {});
  });
}

function bindUnix(server, socketPath) {
  return new Promise((resolve, reject) => {
    const onError = (err) => {
      server.off("listening", onListening);
      reject(err);
    };
    const onListening = () => {
      server.off("error", onError);
      resolve(server);
    };
    server.once("error", onError);
    server.once("listening", onListening);
    server.listen(socketPath);
  });
}

export async function listen(socketPath, handler) {
  if (await pingEngine(socketPath)) {
    throw new Error("engine already listening");
  }
  try {
    const server = await bindUnix(createIpcServer(handler), socketPath);
    fs.chmodSync(socketPath, 0o600);
    return server;
  } catch (err) {
    if (err.code !== "EADDRINUSE") {
      throw err;
    }
    if (await pingEngine(socketPath)) {
      throw new Error("engine already listening");
    }
    try {
      fs.unlinkSync(socketPath);
    } catch {
      /* missing is fine */
    }
    const server = await bindUnix(createIpcServer(handler), socketPath);
    fs.chmodSync(socketPath, 0o600);
    return server;
  }
}

export async function dispatch(player, youtube, req) {
  switch (req.cmd) {
    case "help":
    case "commands":
      return ok({ commands: commandCatalog() });
    case "status":
      return ok(await player.status());
    case "bands":
      return ok({ bands: await player.bands() });
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
    case "automix":
      player.setAutomix(req.name || "toggle");
      return ok({ automix: player.automix });
    case "track.mix":
      await player.startMix(req.track);
      return ok({ total: player.queue.length, index: player.index });
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
      if (Array.isArray(req.tracks) && req.tracks.length) {
        const at = req.index != null ? req.index : req.tracks.findIndex((row) => row?.id === req.track?.id);
        await player.playContext(req.tracks, at);
      } else {
        await player.playTrack(req.track, { replaceQueue: req.replace !== false });
      }
      return ok({ total: player.queue.length, index: player.index });
    case "sleep":
      player.setSleep(req.minutes ?? req.value ?? 0);
      return ok({ sleep_minutes: player.sleepMinutes, sleep_remaining: player.sleepRemaining() });
    case "track.queue":
      player.queueTrack(req.track);
      return ok({ total: player.queue.length, index: player.index });
    case "track.play_next":
      player.playNext(req.track);
      return ok({ total: player.queue.length, index: player.index });
    case "queue.move":
      player.move(req.from, req.to);
      return ok({ tracks: player.queue, index: player.index, total: player.queue.length });
    case "queue.remove":
      player.removeAt(req.index);
      return ok({ tracks: player.queue, index: player.index, total: player.queue.length });
    case "track.liked": {
      const id = videoIdOf(req);
      const result = await youtube.liked(id);
      player.setRating?.(id, result.liked ? "like" : result.disliked ? "dislike" : "indifferent");
      return ok(result);
    }
    case "track.like": {
      const id = videoIdOf(req);
      const result = await youtube.like(id);
      player.setRating?.(id, "like");
      return ok(result);
    }
    case "track.unlike": {
      const id = videoIdOf(req);
      const result = await youtube.unlike(id);
      player.setRating?.(id, "indifferent");
      return ok(result);
    }
    case "track.dislike": {
      const id = videoIdOf(req);
      const result = await youtube.dislike(id);
      player.setRating?.(id, "dislike");
      return ok(result);
    }
    case "playlist.rename": {
      const result = await youtube.renamePlaylist(req.id, req.name);
      return ok(result);
    }
    case "playlist.delete": {
      const result = await youtube.deletePlaylist(req.id);
      return ok(result);
    }
    case "playlist.mix":
      await player.startPlaylistMix(req.id);
      return ok({ total: player.queue.length, index: player.index });
    case "playlist.add":
      await youtube.addToPlaylist(req.playlist_id, req.video_id);
      return ok();
    case "queue.save": {
      const result = await youtube.saveQueue({
        title: req.name || req.title,
        playlistId: req.playlist_id,
        videoIds: player.queue,
      });
      return ok(result);
    }
    case "search": {
      const page = await youtube.search(req.query);
      return ok({ tracks: page.tracks, done: page.done, query: page.query });
    }
    case "search.more": {
      const page = await youtube.searchMore(req.query);
      return ok({ tracks: page.tracks, done: page.done, query: page.query });
    }
    case "playlists": {
      const page = await youtube.playlists();
      return ok({ playlists: page.playlists, done: page.done });
    }
    case "playlists.more": {
      const page = await youtube.playlistsMore();
      return ok({ playlists: page.playlists, done: page.done });
    }
    case "playlist.tracks": {
      const page = await youtube.playlistTracksPage(req.id);
      return ok({ tracks: page.tracks, done: page.done, total: page.tracks.length });
    }
    case "playlist.tracks.more": {
      const page = await youtube.playlistTracksMore(req.id);
      return ok({ tracks: page.tracks, done: page.done, total: page.tracks.length });
    }
    case "playlist.play": {
      const tracks = await youtube.playlistTracks(req.id);
      player.replaceQueue(tracks, req.index || 0);
      if (tracks.length) {
        try {
          await player.playIndex(player.index);
        } catch (err) {
          if (!isUnplayableError(err)) {
            throw err;
          }
          try {
            await player.next();
          } catch (skipErr) {
            if (!isUnplayableError(skipErr)) {
              throw skipErr;
            }
          }
          if (player.state !== "playing") {
            return fail(err.message);
          }
        }
      }
      return ok({ total: tracks.length });
    }
    case "lyrics": {
      const id = String(req.id || player.queue?.[player.index]?.id || "").trim();
      if (!id) {
        return ok({ id: "", text: "", footer: "", found: false });
      }
      const page = await youtube.lyrics(id);
      return ok({
        id,
        text: page.text || "",
        footer: page.footer || "",
        found: Boolean(page.found),
        lines: page.lines || [],
      });
    }
    case "shutdown":
      return ok({ shutdown: true });
    default:
      return fail(`unknown command: ${req.cmd}`);
  }
}
