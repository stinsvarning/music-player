import { setTimeout as delay } from "node:timers/promises";
import { UrlCache } from "./cache.js";
import { PRESETS, dbToUnit, lavfiEqualizer, parseAmetadataLog, spectrumBandFile } from "./eq.js";
import fs from "node:fs";
import { spectrumDir } from "./paths.js";
import { isUnplayableError, unplayableError } from "./playable.js";
import { parseSession } from "./session.js";

export class Player {
  constructor({ mpv, youtube, readBands, persist, cache } = {}) {
    this.mpv = mpv;
    this.youtube = youtube;
    this.persist = persist || null;
    this._restoring = false;
    this.cache = cache || new UrlCache();
    this.queue = [];
    this.index = -1;
    this.shuffle = false;
    this.repeat = "off";
    this.automix = false;
    this.sleepUntil = 0;
    this.sleepMinutes = 0;
    this._extending = null;
    this.eqPreset = "Flat";
    this.eqBands = [...PRESETS.Flat];
    this.volumeLevel = 70;
    this.position = 0;
    this._lastPosSave = 0;
    this.state = "stopped";
    this._ignoreEof = false;
    this._advancing = false;
    this._skipDepth = 0;
    this.readBands = typeof readBands === "function" ? readBands : null;
    this._sleep = delay;
    this._bands = Array(10).fill(0);
    this._bandsUntil = 0;
    this._bandsTimer = null;
    if (typeof this.mpv?.onEvent === "function") {
      this.mpv.onEvent((ev) => this.#onMpvEvent(ev));
    }
  }

  async applyEq() {
    const dir = spectrumDir();
    fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
    await this.mpv.setAf(lavfiEqualizer(this.eqBands, dir));
  }

  async applyVolume() {
    if (typeof this.mpv?.setVolume !== "function") {
      return;
    }
    await this.mpv.setVolume(this.volumeLevel);
  }

  sessionSnapshot() {
    return {
      tracks: this.queue,
      index: this.index,
      shuffle: this.shuffle,
      repeat: this.repeat,
      automix: this.automix,
      volume: this.volumeLevel,
      eq_preset: this.eqPreset,
      eq_bands: [...this.eqBands],
      position: this.position,
      sleep_until: this.sleepUntil,
      sleep_minutes: this.sleepMinutes,
    };
  }

  restoreSession(raw) {
    const session = parseSession(raw);
    if (!session) {
      return false;
    }
    this._restoring = true;
    try {
      this.replaceQueue(session.tracks, session.index);
      this.shuffle = session.shuffle;
      this.repeat = session.repeat;
      this.automix = session.automix;
      this.volumeLevel = session.volume;
      this.eqPreset = session.eq_preset;
      this.eqBands = [...session.eq_bands];
      this.position = session.position;
      this.sleepUntil = session.sleep_until;
      this.sleepMinutes = session.sleep_minutes;
      this.state = "stopped";
    } finally {
      this._restoring = false;
    }
    return true;
  }

  async flushSession() {
    if (this.state !== "stopped" && typeof this.mpv?.get === "function") {
      try {
        const live = await this.mpv.get("time-pos");
        if (live != null) {
          this.position = live;
        }
      } catch {
        /* idle mpv */
      }
    }
    try {
      this.cache?.flush?.();
    } catch {
      /* ignore */
    }
    if (this._restoring || !this.persist) {
      return;
    }
    if (typeof this.persist.save === "function") {
      this.persist.save(this.sessionSnapshot());
    }
    if (typeof this.persist.flush === "function") {
      this.persist.flush();
    }
  }

  #saveSession() {
    if (this._restoring || !this.persist) {
      return;
    }
    const snap = this.sessionSnapshot();
    if (typeof this.persist === "function") {
      this.persist(snap);
      return;
    }
    if (typeof this.persist.save === "function") {
      this.persist.save(snap);
    }
  }

  async playTrack(track, { replaceQueue = false } = {}) {
    if (!track?.id) {
      throw new Error("track id is required");
    }
    if (replaceQueue) {
      this.queue = [normalize(track)];
      this.index = 0;
    } else {
      const existing = this.queue.findIndex((t) => t.id === track.id);
      if (existing >= 0) {
        this.index = existing;
      } else {
        this.queue.push(normalize(track));
        this.index = this.queue.length - 1;
      }
    }
    await this.#loadCurrent();
    this.#saveSession();
  }

  queueTrack(track) {
    if (!track?.id) {
      throw new Error("track id is required");
    }
    this.queue.push(normalize(track));
    if (this.index < 0) {
      this.index = 0;
    }
    this.#saveSession();
  }

  playNext(track) {
    if (!track?.id) {
      throw new Error("track id is required");
    }
    const item = normalize(track);
    const at = this.index < 0 ? 0 : this.index + 1;
    this.queue.splice(at, 0, item);
    if (this.index < 0) {
      this.index = 0;
    }
    this.#saveSession();
  }

  move(from, to) {
    const len = this.queue.length;
    if (!len || from === to) {
      return;
    }
    if (from < 0 || to < 0 || from >= len || to >= len) {
      throw new Error("queue index out of range");
    }
    const currentId = this.index >= 0 ? this.queue[this.index]?.id : null;
    const [item] = this.queue.splice(from, 1);
    this.queue.splice(to, 0, item);
    if (currentId) {
      this.index = this.queue.findIndex((t) => t.id === currentId);
    }
    this.#saveSession();
  }

  removeAt(index) {
    if (index < 0 || index >= this.queue.length) {
      throw new Error("queue index out of range");
    }
    const wasCurrent = index === this.index;
    this.queue.splice(index, 1);
    if (index < this.index) {
      this.index -= 1;
    } else if (wasCurrent) {
      this.index = Math.min(index, this.queue.length - 1);
    }
    if (!this.queue.length) {
      this.index = -1;
      this.state = "stopped";
    }
    this.#saveSession();
  }

  replaceQueue(tracks, startIndex = 0) {
    this.queue = tracks.map(normalize).filter((t) => t.id);
    this.index = this.queue.length ? Math.min(Math.max(0, startIndex), this.queue.length - 1) : -1;
    this.#saveSession();
  }

  async playIndex(index) {
    if (index < 0 || index >= this.queue.length) {
      throw new Error("queue index out of range");
    }
    this.index = index;
    await this.#loadCurrent();
    this.#saveSession();
  }

  async next() {
    if (!this.queue.length) {
      return;
    }
    if (this.repeat === "one") {
      this.position = 0;
      try {
        await this.#loadCurrent({ keepPosition: true });
      } catch (err) {
        if (isUnplayableError(err)) {
          await this.#stopAtEnd();
        }
        throw err;
      }
      this.#saveSession();
      return;
    }
    if (this.index + 1 < this.queue.length) {
      this.index += 1;
    } else if (this.repeat === "all") {
      if (this.shuffle) {
        this.#shuffleRest({ wrap: true });
      } else {
        this.index = 0;
      }
    } else if (this.automix) {
      const added = await this.#extendRadio();
      if (!added) {
        await this.#stopAtEnd();
        return;
      }
      this.index += 1;
    } else {
      await this.#stopAtEnd();
      return;
    }
    this.position = 0;
    try {
      await this.#loadCurrent({ keepPosition: true });
    } catch (err) {
      if (!isUnplayableError(err)) {
        throw err;
      }
      this._skipDepth = (this._skipDepth || 0) + 1;
      if (this._skipDepth > this.queue.length) {
        this._skipDepth = 0;
        await this.#stopAtEnd();
        throw unplayableError("no playable tracks in the queue");
      }
      try {
        await this.next();
      } finally {
        this._skipDepth = Math.max(0, (this._skipDepth || 1) - 1);
      }
      return;
    }
    this.#saveSession();
  }

  async prev() {
    if (!this.queue.length) {
      return;
    }
    this.index = this.index > 0 ? this.index - 1 : 0;
    this.position = 0;
    await this.#loadCurrent({ keepPosition: true });
    this.#saveSession();
  }

  async #fileLoaded() {
    if (typeof this.mpv?.get !== "function") {
      return this.state !== "stopped";
    }
    try {
      return (await this.mpv.get("idle-active")) === false;
    } catch {
      return this.state !== "stopped";
    }
  }

  #atTrackEnd() {
    const track = this.queue[this.index];
    const dur = Number(track?.duration_secs) || 0;
    const pos = Number(this.position) || 0;
    return dur > 0 && pos >= Math.max(0, dur - 1);
  }

  async #stopAtEnd() {
    this.position = 0;
    this.state = "stopped";
    await this.mpv.pause(true);
    this.#saveSession();
  }

  async #loadIfIdle() {
    if (this.index < 0) {
      this.index = 0;
    }
    if (this.#atTrackEnd()) {
      this.position = 0;
    }
    await this.#loadCurrent({ keepPosition: true });
  }

  async toggle() {
    if (!this.queue.length) {
      return;
    }
    if (!(await this.#fileLoaded())) {
      await this.#loadIfIdle();
      return;
    }
    const paused = this.state !== "playing";
    await this.mpv.pause(!paused ? true : false);
    this.state = paused ? "playing" : "paused";
    this.#saveSession();
  }

  async play() {
    if (!this.queue.length) {
      return;
    }
    if (!(await this.#fileLoaded())) {
      await this.#loadIfIdle();
      return;
    }
    await this.mpv.pause(false);
    this.state = "playing";
  }

  async pause() {
    await this.mpv.pause(true);
    if (this.state === "playing") {
      this.state = "paused";
    }
    this.#saveSession();
  }

  async stop() {
    await this.mpv.pause(true);
    this.state = "stopped";
    this.#saveSession();
  }

  async seek(seconds) {
    const n = Number(seconds);
    this.position = Number.isFinite(n) && n > 0 ? n : 0;
    if (typeof this.mpv?.seekAbsolute === "function") {
      await this.mpv.seekAbsolute(this.position);
    }
    this.#saveSession();
  }

  async bands() {
    this._bandsUntil = Date.now() + 400;
    if (this.state !== "playing") {
      this._bands = Array(10).fill(0);
      return [...this._bands];
    }
    this.#ensureBandsTimer();
    return [...this._bands];
  }

  stopBands() {
    if (this._bandsTimer) {
      clearInterval(this._bandsTimer);
      this._bandsTimer = null;
    }
  }

  #sampleBands() {
    const reader = typeof this.readBands === "function" ? this.readBands : () => readSpectrumBands(spectrumDir());
    const next = reader();
    this._bands = Array.isArray(next) && next.length ? next.slice(0, 10) : Array(10).fill(0);
    while (this._bands.length < 10) {
      this._bands.push(0);
    }
  }

  #ensureBandsTimer() {
    if (this._bandsTimer) {
      return;
    }
    this.#sampleBands();
    this._bandsTimer = setInterval(() => {
      if (Date.now() > this._bandsUntil) {
        this.stopBands();
        return;
      }
      if (this.state !== "playing") {
        this._bands = Array(10).fill(0);
        return;
      }
      this.#sampleBands();
    }, 80);
    this._bandsTimer.unref?.();
  }

  async volume(value) {
    const n = Number(value);
    this.volumeLevel = Number.isFinite(n) ? Math.max(0, Math.min(100, n)) : 70;
    if (typeof this.mpv?.setVolume === "function") {
      await this.mpv.setVolume(this.volumeLevel);
    }
    this.#saveSession();
  }

  setShuffle(name) {
    if (name === "on") {
      this.shuffle = true;
    } else if (name === "off") {
      this.shuffle = false;
    } else {
      this.shuffle = !this.shuffle;
    }
    if (this.shuffle) {
      this.#shuffleRest();
    }
    this.#saveSession();
  }

  setSleep(minutes) {
    const value = Number(minutes);
    if (!Number.isFinite(value) || value <= 0) {
      this.sleepUntil = 0;
      this.sleepMinutes = 0;
      this.#saveSession();
      return;
    }
    this.sleepMinutes = value;
    this.sleepUntil = Date.now() + value * 60 * 1000;
    this.#saveSession();
  }

  sleepRemaining() {
    if (!this.sleepUntil) {
      return 0;
    }
    return Math.max(0, Math.ceil((this.sleepUntil - Date.now()) / 1000));
  }

  async #expireSleep() {
    if (!this.sleepUntil || Date.now() < this.sleepUntil) {
      return;
    }
    this.sleepUntil = 0;
    this.sleepMinutes = 0;
    this.#saveSession();
    await this.stop();
  }

  setAutomix(name) {
    if (name === "on") {
      this.automix = true;
    } else if (name === "off") {
      this.automix = false;
    } else {
      this.automix = !this.automix;
    }
    this.#saveSession();
  }

  async startMix(track) {
    if (!track?.id) {
      throw new Error("track id is required");
    }
    if (typeof this.youtube.mix !== "function") {
      throw new Error("mix is not available");
    }
    const mix = await this.youtube.mix(track.id);
    await this.#applyMix(mix, track.id);
  }

  async startPlaylistMix(playlistId) {
    const id = String(playlistId || "").trim();
    if (!id) {
      throw new Error("playlist id is required");
    }
    if (typeof this.youtube.mixPlaylist !== "function") {
      throw new Error("mix is not available");
    }
    const mix = await this.youtube.mixPlaylist(id);
    await this.#applyMix(mix);
  }

  async #applyMix(mix, seedId = "") {
    const tracks = (mix?.tracks || []).map(normalize).filter((t) => t.id);
    if (!tracks.length) {
      throw new Error("mix returned no tracks");
    }
    const seed = seedId ? tracks.findIndex((t) => t.id === seedId) : 0;
    this.queue = tracks;
    this.index = seed >= 0 ? seed : 0;
    this.automix = true;
    await this.#loadCurrent();
    this.#saveSession();
  }

  setRating(id, rating) {
    const want = String(id || "").trim();
    if (!want) {
      return;
    }
    const liked = rating === "like";
    const disliked = rating === "dislike";
    for (const track of this.queue) {
      if (track.id === want) {
        track.liked = liked;
        track.disliked = disliked;
      }
    }
  }

  setRepeat(name) {
    if (name === "cycle") {
      this.repeat = this.repeat === "off" ? "all" : this.repeat === "all" ? "one" : "off";
      this.#saveSession();
      return;
    }
    if (["off", "all", "one"].includes(name)) {
      this.repeat = name;
      this.#saveSession();
    }
  }

  async setEqPreset(name) {
    const bands = PRESETS[name];
    if (!bands) {
      throw new Error(`unknown EQ preset ${name}`);
    }
    this.eqPreset = name;
    this.eqBands = [...bands];
    await this.applyEq();
    this.#saveSession();
  }

  async setEqBand(index, value) {
    if (index < 0 || index > 9) {
      throw new Error("EQ band must be 0-9");
    }
    this.eqBands[index] = Number(value);
    this.eqPreset = "Custom";
    await this.applyEq();
    this.#saveSession();
  }

  async status() {
    await this.#expireSleep();
    let position = this.position;
    let duration = 0;
    let volume = this.volumeLevel;
    let paused = true;
    let idle = null;
    try {
      duration = (await this.mpv.get("duration")) || 0;
      const live = await this.mpv.get("volume");
      if (live != null) {
        volume = live;
      }
      paused = await this.mpv.get("pause");
      idle = await this.mpv.get("idle-active");
      if (paused === false && idle === false && this.queue.length) {
        this.state = "playing";
      }
      if (this.state !== "stopped") {
        const livePos = await this.mpv.get("time-pos");
        if (livePos != null) {
          position = livePos;
          this.position = livePos;
          this.#maybeSavePosition();
        }
      }
    } catch {
      /* idle mpv */
    }
    if (this.state !== "stopped") {
      if (idle === true) {
        this.state = "paused";
      } else {
        this.state = paused ? "paused" : "playing";
      }
    }
    const track = this.queue[this.index] || null;
    return {
      state: this.state,
      track,
      position,
      duration: duration || track?.duration_secs || 0,
      volume,
      index: this.index,
      total: this.queue.length,
      shuffle: this.shuffle,
      repeat: this.repeat,
      automix: this.automix,
      sleep_remaining: this.sleepRemaining(),
      sleep_minutes: this.sleepMinutes,
      eq_preset: this.eqPreset,
      eq_bands: [...this.eqBands],
      liked: track?.liked === true ? true : track?.liked === false ? false : null,
      disliked: track?.disliked === true ? true : track?.disliked === false ? false : null,
      queue_sig: `${this.index}:${this.queue.map((t) => t.id).join(",")}`,
      logged_in: Boolean(this.youtube?.loggedIn),
      auth_source: this.youtube?.authSource || "",
      auth_error: this.youtube?.authError || "",
    };
  }

  prefetchNext() {
    const next = this.queue[this.index + 1];
    if (next?.id) {
      if (!this.cache.get(next.id)) {
        this.#resolve(next.id).catch(() => {});
      }
      return;
    }
    if (this.automix && this.repeat === "off") {
      this.#extendRadio()
        .then((added) => {
          if (added) {
            const upcoming = this.queue[this.index + 1];
            if (upcoming?.id && !this.cache.get(upcoming.id)) {
              return this.#resolve(upcoming.id);
            }
          }
          return null;
        })
        .catch(() => {});
    }
  }

  async #extendRadio() {
    if (this._extending) {
      return this._extending;
    }
    this._extending = this.#extendRadioInner().finally(() => {
      this._extending = null;
    });
    return this._extending;
  }

  async #extendRadioInner() {
    if (typeof this.youtube.similar !== "function") {
      return 0;
    }
    const seed = this.queue[this.index] || this.queue[this.queue.length - 1];
    if (!seed?.id) {
      return 0;
    }
    const have = this.queue.map((t) => t.id);
    const extra = await this.youtube.similar(seed.id, { exclude: have });
    const fresh = (extra || []).map(normalize).filter((t) => t.id && !have.includes(t.id));
    if (!fresh.length) {
      return 0;
    }
    this.queue.push(...fresh);
    this.#saveSession();
    return fresh.length;
  }

  async #resumeSeek(target) {
    const seconds = Number(target);
    if (!(seconds > 0.5) || typeof this.mpv.seekAbsolute !== "function") {
      return;
    }
    const sleep = typeof this._sleep === "function" ? this._sleep : delay;
    for (let attempt = 0; attempt < 12; attempt += 1) {
      try {
        await this.mpv.seekAbsolute(seconds);
        if (typeof this.mpv.get === "function") {
          const pos = await this.mpv.get("time-pos");
          if (pos != null && pos + 2 < seconds) {
            await sleep(80);
            continue;
          }
        }
        return;
      } catch {
        await sleep(80);
      }
    }
  }

  async #loadCurrent({ keepPosition = false } = {}) {
    const track = this.queue[this.index];
    if (!track) {
      throw new Error("nothing to play");
    }
    if (!keepPosition) {
      this.position = 0;
    }
    this._ignoreEof = true;
    try {
      const cached = this.cache.get(track.id);
      let url = cached || (await this.#resolve(track.id));
      try {
        await this.mpv.load(url);
      } catch (err) {
        if (!cached) {
          throw err;
        }
        this.cache.drop(track.id);
        url = await this.#resolve(track.id);
        await this.mpv.load(url);
      }
      this.state = "playing";
      await this.#resumeSeek(this.position);
      await this.mpv.pause(false);
      this.prefetchNext();
      this.#refreshRating(track.id);
    } catch (err) {
      if (isUnplayableError(err) && this.queue[this.index]) {
        this.queue[this.index].playable = false;
      }
      throw err;
    } finally {
      setTimeout(() => {
        this._ignoreEof = false;
      }, 400);
    }
  }

  #refreshRating(id) {
    const want = String(id || "").trim();
    if (!want || typeof this.youtube?.liked !== "function") {
      return;
    }
    const apply = (result) => {
      if (!result || this.queue[this.index]?.id !== want) {
        return;
      }
      this.setRating(want, result.liked ? "like" : result.disliked ? "dislike" : "indifferent");
    };
    this.youtube.liked(want).then(apply).catch(() => {});
    if (typeof this.youtube.whenLikedIds === "function") {
      this.youtube
        .whenLikedIds()
        .then(() => this.youtube.liked(want))
        .then(apply)
        .catch(() => {});
    }
  }

  #maybeSavePosition() {
    const now = Date.now();
    if (now - this._lastPosSave < 5000) {
      return;
    }
    this._lastPosSave = now;
    this.#saveSession();
  }

  #onMpvEvent(ev) {
    if (!ev || ev.event !== "end-file") {
      return;
    }
    if (this._ignoreEof || this._advancing) {
      return;
    }
    if (ev.reason && ev.reason !== "eof") {
      return;
    }
    this._advancing = true;
    this.next()
      .catch(() => {})
      .finally(() => {
        this._advancing = false;
      });
  }

  #shuffleRest({ wrap = false } = {}) {
    if (this.queue.length < 2) {
      return;
    }
    if (wrap) {
      fisherYates(this.queue);
      this.index = 0;
      return;
    }
    if (this.index < 0) {
      fisherYates(this.queue);
      return;
    }
    const head = this.queue.slice(0, this.index + 1);
    const tail = this.queue.slice(this.index + 1);
    fisherYates(tail);
    this.queue = [...head, ...tail];
  }

  async #resolve(videoId) {
    const cached = this.cache.get(videoId);
    if (cached) {
      return cached;
    }
    const url = await this.youtube.streamUrl(videoId);
    this.cache.set(videoId, url);
    return url;
  }
}

function readSpectrumBands(dir) {
  const bands = [];
  for (let i = 0; i < 10; i += 1) {
    bands.push(readSpectrumBand(spectrumBandFile(dir, i)));
  }
  return bands;
}

function readSpectrumBand(filePath) {
  try {
    const stat = fs.statSync(filePath);
    const fd = fs.openSync(filePath, "r");
    try {
      const size = Math.min(stat.size, 2048);
      const buf = Buffer.alloc(size);
      fs.readSync(fd, buf, 0, size, Math.max(0, stat.size - size));
      const parsed = parseAmetadataLog(buf.toString("utf8"));
      const raw = parsed["lavfi.astats.Overall.RMS_level"];
      if (stat.size > 16000) {
        try {
          fs.truncateSync(filePath, 0);
        } catch {
          /* writer still has the handle */
        }
      }
      return dbToUnit(Number(raw));
    } finally {
      fs.closeSync(fd);
    }
  } catch {
    return 0;
  }
}

function fisherYates(items) {
  for (let i = items.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [items[i], items[j]] = [items[j], items[i]];
  }
  return items;
}

function normalize(track) {
  return {
    id: track.id,
    title: track.title || track.id,
    artist: track.artist || "",
    album: track.album || "",
    duration_secs: Number(track.duration_secs || 0),
    path: track.path || `https://music.youtube.com/watch?v=${track.id}`,
    playable: track.playable !== false,
  };
}
