import { Agent, fetch as undiciFetch } from "undici";
import { BG } from "bgutils-js";
import { Window } from "happy-dom";
import { Innertube, Log, Platform, UniversalCache } from "youtubei.js";

try {
  Log.setLevel(Log.Level.NONE);
} catch {
  /* older youtubei.js */
}

Platform.shim.eval = async (data) => {
  const src = typeof data === "string" ? data : data.output;
  return new Function(src)();
};
import { pickAudioFormat } from "./formats.js";

const http1 = new Agent({ allowH2: false });

function ytFetch(input, init = {}) {
  if (typeof input === "string" || input instanceof URL) {
    return undiciFetch(input, { ...init, dispatcher: http1 });
  }
  const url = input.url;
  const method = init.method || input.method;
  const headers = init.headers || input.headers;
  const body = init.body !== undefined ? init.body : input.body;
  return undiciFetch(url, { ...init, method, headers, body, dispatcher: http1 });
}

const BOTGUARD_KEY = "O43z0dpjhgX20SCx4KAo";

export class Youtube {
  constructor() {
    this.yt = null;
  }

  async connect(cookieHeader) {
    if (!cookieHeader) {
      throw new Error("no YouTube cookies — open Zen, stay logged into YouTube Music, restart");
    }
    this.yt = await Innertube.create({
      cache: new UniversalCache(false),
      cookie: cookieHeader,
      generate_session_locally: true,
      fetch: ytFetch,
    });
    try {
      await this.#applyPoToken();
    } catch (err) {
      console.error("poToken skipped:", err.message || err);
    }
  }

  async search(query, limit = 20) {
    const res = await this.yt.music.search(query, { type: "song" });
    return takeSongs(res?.songs?.contents || res?.contents || [], limit);
  }

  async playlists() {
    const lib = await this.yt.music.getLibrary();
    const items = [];
    collect(lib.contents, items);
    return items
      .filter((it) => it.item_type === "playlist" || it.playlist_id || (it.id && String(it.id).startsWith("PL")))
      .map((it) => ({
        id: it.id || it.playlist_id,
        name: it.title || it.name || "playlist",
        track_count: parseCount(it.item_count || it.song_count),
      }))
      .filter((p) => p.id);
  }

  async playlistTracks(id) {
    const pl = await this.yt.music.getPlaylist(id);
    const contents = pl.videos || pl.items || pl.contents || [];
    return takeSongs(contents, 500);
  }

  async streamUrl(videoId) {
    let info;
    try {
      info = await this.yt.music.getInfo(videoId);
    } catch (err) {
      await this.#applyPoToken();
      info = await this.yt.music.getInfo(videoId);
      if (!info) {
        throw err;
      }
    }
    const formats = [
      ...(info.streaming_data?.adaptive_formats || []),
      ...(info.streaming_data?.formats || []),
    ];
    const picked = pickAudioFormat(formats);
    if (!picked) {
      throw new Error("no audio format from YouTube Music");
    }
    const url = await picked.decipher(this.yt.session.player);
    if (!url) {
      throw new Error("could not decipher audio url");
    }
    return url;
  }

  async #applyPoToken() {
    const visitorData = this.yt.session.context.client.visitorData;
    if (!visitorData) {
      return;
    }
    const window = new Window({ width: 800, height: 600 });
    const document = window.document;
    const prevWindow = globalThis.window;
    const prevDocument = globalThis.document;
    Object.assign(globalThis, { window, document });
    try {
      const bgConfig = {
        fetch: ytFetch,
        globalObj: globalThis,
        identifier: visitorData,
        requestKey: BOTGUARD_KEY,
      };
      const challenge = await BG.Challenge.create(bgConfig);
      const interpreter =
        challenge?.interpreterJavascript?.privateDoNotAccessOrElseSafeScriptWrappedValue;
      if (!interpreter) {
        return;
      }
      // Botguard ships an interpreter snippet that must run in this realm.
      new Function(interpreter)();
      const token = await BG.PoToken.generate({
        program: challenge.program,
        globalName: challenge.globalName,
        bgConfig,
      });
      if (token?.poToken) {
        this.yt.session.po_token = token.poToken;
      }
    } finally {
      if (prevWindow === undefined) {
        delete globalThis.window;
      } else {
        globalThis.window = prevWindow;
      }
      if (prevDocument === undefined) {
        delete globalThis.document;
      } else {
        globalThis.document = prevDocument;
      }
      window.close();
    }
  }
}

function collect(node, out) {
  if (!node) {
    return;
  }
  if (Array.isArray(node)) {
    for (const child of node) {
      collect(child, out);
    }
    return;
  }
  if (node.contents) {
    collect(node.contents, out);
  }
  if (node.items) {
    collect(node.items, out);
  }
  if (node.item_type || node.id || node.title) {
    out.push(node);
  }
}

function takeSongs(nodes, limit) {
  const songs = [];
  const walk = (list) => {
    if (!list) {
      return;
    }
    const arr = Array.isArray(list) ? list : list.contents || list.items || [];
    for (const it of arr) {
      if (songs.length >= limit) {
        return;
      }
      if (it?.contents || it?.items) {
        walk(it);
        continue;
      }
      const id = it.id || it.video_id;
      const type = it.item_type;
      if (!id) {
        continue;
      }
      if (type && type !== "song" && type !== "video") {
        continue;
      }
      songs.push({
        id,
        title: it.title || it.name || id,
        artist: (it.artists && it.artists[0]?.name) || it.author?.name || "",
        album: it.album?.name || "",
        duration_secs: it.duration?.seconds || 0,
      });
    }
  };
  walk(nodes);
  return songs;
}

function parseCount(text) {
  if (!text) {
    return 0;
  }
  const n = parseInt(String(text).replace(/[^\d]/g, ""), 10);
  return Number.isFinite(n) ? n : 0;
}
