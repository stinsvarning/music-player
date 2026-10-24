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
import { looksLikeAuthError } from "./auth-error.js";
import { LOGIN_REQUIRED } from "./cookies.js";
import { pickAudioFormat } from "./formats.js";
import { infoLooksUnplayable, isUnplayableError, unplayableError } from "./playable.js";
import { saveQueue } from "./save-queue.js";
import {
  continuePlaylistCollection,
  deletePlaylistRequest,
  playlistIsEditable,
  renamePlaylistRequest,
  startPlaylistCollection,
} from "./library.js";
import { likeStatusFromInfo, mergeLikeStatus, rateTrack } from "./like.js";
import {
  collectAllTracks,
  continueSearchCollection,
  continueTrackCollection,
  extractSongs,
  panelSongs,
  playlistRadioId,
  songRadioId,
  startSearchCollection,
  startTrackCollection,
  uniqueAfter,
} from "./mix.js";
import { parseLyrics } from "./lyrics.js";
import { innertubeCacheDir } from "./paths.js";
import { playlistEditId, textOf } from "./text.js";

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
    this.loggedIn = false;
    this.authSource = "";
    this.authError = "";
    this._playlistSession = null;
    this._trackSession = null;
    this._searchSession = null;
    this._cookie = "";
    this._likeCache = new Map();
    this._likedIds = null;
    this._likedLoad = null;
    this._infoMemo = new Map();
    this.onAuthExpired = null;
  }

  async #withAuthRetry(fn) {
    try {
      return await fn();
    } catch (err) {
      if (!looksLikeAuthError(err) || typeof this.onAuthExpired !== "function") {
        throw err;
      }
      await this.onAuthExpired();
      this.#requireLogin();
      return await fn();
    }
  }

  disconnect() {
    this.yt = null;
    this.loggedIn = false;
    this.authSource = "";
    this._cookie = "";
    this._playlistSession = null;
    this._trackSession = null;
    this._searchSession = null;
    this._likeCache = new Map();
    this._likedIds = null;
    this._likedLoad = null;
    this._infoMemo = new Map();
  }

  #requireLogin() {
    if (!this.yt) {
      throw new Error(LOGIN_REQUIRED);
    }
  }

  async connect(cookieHeader) {
    if (!cookieHeader) {
      this.disconnect();
      this.authError = LOGIN_REQUIRED;
      throw new Error(LOGIN_REQUIRED);
    }
    this._cookie = cookieHeader;
    this._playlistSession = null;
    this._trackSession = null;
    this._searchSession = null;
    this._likedIds = null;
    this._likedLoad = null;
    this._infoMemo = new Map();
    this.yt = await Innertube.create({
      cache: new UniversalCache(true, innertubeCacheDir()),
      cookie: cookieHeader,
      generate_session_locally: true,
      fetch: ytFetch,
    });
    this.loggedIn = true;
    this.authError = "";
    try {
      await Promise.race([
        this.#applyPoToken(),
        new Promise((_, reject) => {
          setTimeout(() => reject(new Error("poToken timeout")), 4000);
        }),
      ]);
    } catch (err) {
      console.error("poToken skipped:", err.message || err);
    }
  }

  async search(query) {
    return this.#withAuthRetry(async () => {
      this.#requireLogin();
      const q = String(query || "").trim();
      if (!q) {
        this._searchSession = null;
        return { tracks: [], done: true, query: "" };
      }
      const res = await this.yt.music.search(q, { type: "song" });
      const session = startSearchCollection(res);
      this._searchSession = { query: q, pages: 1, ...session };
      return { tracks: session.tracks, done: session.done, query: q };
    });
  }

  async searchMore(query) {
    if (!this._searchSession || this._searchSession.done) {
      return { tracks: [], done: true, query: this._searchSession?.query || "" };
    }
    if (query && query !== this._searchSession.query) {
      return { tracks: [], done: true, query: this._searchSession.query };
    }
    if ((this._searchSession.pages || 1) >= 20) {
      return { tracks: [], done: true, query: this._searchSession.query };
    }
    const session = await continueSearchCollection(this._searchSession);
    this._searchSession = {
      query: this._searchSession.query,
      pages: (this._searchSession.pages || 1) + 1,
      ...session,
    };
    return {
      tracks: session.tracks,
      done: session.done || this._searchSession.pages >= 20,
      query: this._searchSession.query,
    };
  }

  async playlists() {
    return this.#withAuthRetry(async () => {
      this.#requireLogin();
      const lib = await this.yt.music.getLibrary();
      this._playlistSession = await startPlaylistCollection(lib);
      return {
        playlists: this._playlistSession.playlists,
        done: this._playlistSession.done,
      };
    });
  }

  async playlistsMore() {
    if (!this._playlistSession || this._playlistSession.done) {
      return { playlists: [], done: true };
    }
    this._playlistSession = await continuePlaylistCollection(this._playlistSession);
    return {
      playlists: this._playlistSession.playlists,
      done: this._playlistSession.done,
    };
  }

  async playlistTracks(id) {
    return this.#withAuthRetry(async () => {
      this.#requireLogin();
      const pl = await this.yt.music.getPlaylist(id);
      return collectAllTracks(pl);
    });
  }

  async playlistTracksPage(id) {
    return this.#withAuthRetry(async () => {
      this.#requireLogin();
      const pl = await this.yt.music.getPlaylist(id);
      const session = startTrackCollection(pl);
      this._trackSession = { id, ...session };
      return { tracks: session.tracks, done: session.done };
    });
  }

  async playlistTracksMore(id) {
    if (!this._trackSession || this._trackSession.done) {
      return { tracks: [], done: true };
    }
    if (id && id !== this._trackSession.id) {
      return { tracks: [], done: true };
    }
    const session = await continueTrackCollection(this._trackSession);
    this._trackSession = { id: this._trackSession.id, ...session };
    return { tracks: session.tracks, done: session.done };
  }

  async mix(videoId) {
    return this.#withAuthRetry(async () => {
    this.#requireLogin();
    const id = textOf(videoId);
    if (!id) {
      throw new Error("track id is required");
    }
    let tracks = [];
    let title = "Mix";
    try {
      const panel = await this.yt.music.getUpNext(id, true);
      tracks = panelSongs(panel, 50);
      title = textOf(panel?.title) || textOf(panel?.title_text) || "Mix";
    } catch {
      /* fall through to radio playlist */
    }
    if (tracks.length < 2) {
      try {
        const pl = await this.yt.music.getPlaylist(songRadioId(id));
        tracks = extractSongs(pl.videos || pl.items || pl.contents || []).slice(0, 50);
      } catch {
        /* keep whatever we have */
      }
    }
    if (!tracks.some((t) => t.id === id)) {
      tracks.unshift({
        id,
        title: id,
        artist: "",
        album: "",
        duration_secs: 0,
      });
    } else {
      const idx = tracks.findIndex((t) => t.id === id);
      if (idx > 0) {
        const [seed] = tracks.splice(idx, 1);
        tracks.unshift(seed);
      }
    }
    if (!tracks.length) {
      throw new Error("could not start a mix for this song");
    }
    return { tracks, title, playlist_id: songRadioId(id) };
    });
  }

  async similar(videoId, { exclude = [] } = {}) {
    const mix = await this.mix(videoId);
    return uniqueAfter(mix.tracks, exclude);
  }

  async like(videoId) {
    this.#requireLogin();
    const result = await rateTrack({
      execute: (endpoint, body) => this.yt.actions.execute(endpoint, body),
      videoId,
      liked: true,
    });
    this._likedIds?.add(result.id);
    this._likeCache.set(result.id, result);
    return result;
  }

  async unlike(videoId) {
    this.#requireLogin();
    const result = await rateTrack({
      execute: (endpoint, body) => this.yt.actions.execute(endpoint, body),
      videoId,
      liked: false,
    });
    this._likedIds?.delete(result.id);
    this._likeCache.set(result.id, result);
    return result;
  }

  async dislike(videoId) {
    this.#requireLogin();
    const id = textOf(videoId);
    if (!id) {
      throw new Error("track id is required");
    }
    await this.yt.interact.dislike(id);
    this._likedIds?.delete(id);
    const result = { id, liked: false, disliked: true };
    this._likeCache.set(id, result);
    return result;
  }

  whenLikedIds() {
    this.#ensureLikedIds();
    return this._likedLoad || Promise.resolve();
  }

  async liked(videoId) {
    this.#requireLogin();
    const id = textOf(videoId);
    if (!id) {
      throw new Error("track id is required");
    }
    this.#ensureLikedIds();
    if (this._likedIds?.has(id)) {
      const result = { id, liked: true, disliked: false };
      this._likeCache.set(id, result);
      return result;
    }
    if (this._likeCache.has(id)) {
      return { id, ...this._likeCache.get(id) };
    }
    let fromInfo = { liked: null, disliked: null };
    try {
      fromInfo = likeStatusFromInfo(await this.#trackInfo(id));
    } catch {
      /* library membership is enough */
    }
    const merged = mergeLikeStatus(id, this._likedIds, fromInfo);
    const result = {
      id,
      liked: merged.liked === true,
      disliked: merged.disliked === true,
    };
    this._likeCache.set(id, result);
    return result;
  }

  #ensureLikedIds() {
    if (this._likedLoad) {
      return;
    }
    this._likedLoad = this.playlistTracks("LM")
      .then((tracks) => {
        this._likedIds = new Set((tracks || []).map((row) => row.id).filter(Boolean));
        return this._likedIds;
      })
      .catch(() => {
        this._likedIds = this._likedIds || new Set();
        return this._likedIds;
      });
  }

  async renamePlaylist(playlistId, name) {
    this.#requireLogin();
    const id = playlistEditId(playlistId);
    if (!playlistIsEditable(id)) {
      throw new Error("this playlist cannot be renamed");
    }
    return renamePlaylistRequest({
      execute: (endpoint, body) => this.yt.actions.execute(endpoint, body),
      playlistId: id,
      name,
    });
  }

  async deletePlaylist(playlistId) {
    this.#requireLogin();
    const id = playlistEditId(playlistId);
    if (!playlistIsEditable(id)) {
      throw new Error("this playlist cannot be deleted");
    }
    return deletePlaylistRequest({
      execute: (endpoint, body) => this.yt.actions.execute(endpoint, body),
      playlistId: id,
    });
  }

  async mixPlaylist(playlistId) {
    this.#requireLogin();
    const radio = playlistRadioId(playlistId);
    if (!radio) {
      throw new Error("playlist id is required");
    }
    let tracks = [];
    let title = "Mix";
    try {
      const pl = await this.yt.music.getPlaylist(radio);
      tracks = extractSongs(pl.videos || pl.items || pl.contents || []).slice(0, 50);
      title = textOf(pl.title) || textOf(pl.header?.title) || textOf(pl.info?.title) || "Mix";
    } catch {
      /* fall through to a seed-track mix */
    }
    if (tracks.length < 2) {
      const source = await this.playlistTracks(playlistId);
      const seed = source.find((row) => row.playable !== false) || source[0];
      if (!seed?.id) {
        throw new Error("could not start a mix for this playlist");
      }
      return this.mix(seed.id);
    }
    return { tracks, title, playlist_id: radio };
  }

  async addToPlaylist(playlistId, videoId) {
    this.#requireLogin();
    const id = playlistEditId(playlistId);
    const video = textOf(videoId);
    if (!id || !video) {
      throw new Error("playlist and video id are required");
    }
    await this.yt.playlist.addVideos(id, [video]);
    return { playlist_id: id, video_id: video };
  }

  async lyrics(videoId) {
    this.#requireLogin();
    const id = String(videoId || "").trim();
    if (!id) {
      throw new Error("track id is required");
    }
    try {
      return parseLyrics(await this.yt.music.getLyrics(id));
    } catch {
      return { text: "", footer: "", found: false, lines: [] };
    }
  }

  async saveQueue({ title, playlistId, videoIds }) {
    this.#requireLogin();
    return saveQueue({
      title,
      playlistId,
      videoIds,
      create: (name, ids) => this.yt.playlist.create(name, ids),
      addVideos: (id, ids) => this.yt.playlist.addVideos(id, ids),
    });
  }

  async #trackInfo(videoId, { fresh = false } = {}) {
    const id = String(videoId || "").trim();
    const now = Date.now();
    if (!fresh) {
      const hit = this._infoMemo.get(id);
      if (hit && hit.until > now) {
        return hit.info;
      }
    }
    const info = await this.yt.music.getInfo(id);
    this._infoMemo.set(id, { info, until: now + 20_000 });
    while (this._infoMemo.size > 24) {
      const oldest = this._infoMemo.keys().next().value;
      this._infoMemo.delete(oldest);
    }
    return info;
  }

  async streamUrl(videoId) {
    this.#requireLogin();
    const id = String(videoId || "").trim();
    if (!id) {
      throw new Error("track id is required");
    }
    let lastError = new Error("no audio format from YouTube Music");
    for (let attempt = 0; attempt < 3; attempt += 1) {
      if (attempt === 1) {
        await this.#applyPoToken();
      }
      if (attempt === 2 && this._cookie) {
        await this.connect(this._cookie);
      }
      let info;
      try {
        info = await this.#trackInfo(id, { fresh: attempt > 0 });
      } catch (err) {
        if (isUnplayableError(err)) {
          throw err;
        }
        lastError = err;
        continue;
      }
      const blocked = infoLooksUnplayable(info);
      if (blocked) {
        throw unplayableError(blocked);
      }
      const formats = [
        ...(info.streaming_data?.adaptive_formats || []),
        ...(info.streaming_data?.formats || []),
      ];
      const picked = pickAudioFormat(formats);
      if (!picked) {
        lastError = new Error("no audio format from YouTube Music");
        continue;
      }
      const kbps = Math.round(Number(picked.average_bitrate || picked.bitrate || 0) / 1000);
      console.error(`audio itag=${picked.itag} ${picked.audio_quality || "unknown"} ${kbps}kbps`);
      const url = await picked.decipher(this.yt.session.player);
      if (!url) {
        lastError = new Error("could not decipher audio url");
        continue;
      }
      return url;
    }
    throw lastError;
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

