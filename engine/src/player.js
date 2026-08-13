import { UrlCache } from "./cache.js";
import { PRESETS, lavfiEqualizer } from "./eq.js";

export class Player {
  constructor({ mpv, youtube }) {
    this.mpv = mpv;
    this.youtube = youtube;
    this.cache = new UrlCache();
    this.queue = [];
    this.index = -1;
    this.shuffle = false;
    this.repeat = "off";
    this.eqPreset = "Flat";
    this.eqBands = [...PRESETS.Flat];
    this.state = "stopped";
  }

  async applyEq() {
    await this.mpv.setAf(lavfiEqualizer(this.eqBands));
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
  }

  queueTrack(track) {
    if (!track?.id) {
      throw new Error("track id is required");
    }
    this.queue.push(normalize(track));
    if (this.index < 0) {
      this.index = 0;
    }
  }

  replaceQueue(tracks, startIndex = 0) {
    this.queue = tracks.map(normalize).filter((t) => t.id);
    this.index = this.queue.length ? Math.min(Math.max(0, startIndex), this.queue.length - 1) : -1;
  }

  async playIndex(index) {
    if (index < 0 || index >= this.queue.length) {
      throw new Error("queue index out of range");
    }
    this.index = index;
    await this.#loadCurrent();
  }

  async next() {
    if (!this.queue.length) {
      return;
    }
    if (this.repeat === "one") {
      await this.#loadCurrent();
      return;
    }
    if (this.index + 1 < this.queue.length) {
      this.index += 1;
    } else if (this.repeat === "all") {
      this.index = 0;
    } else {
      this.state = "stopped";
      await this.mpv.pause(true);
      return;
    }
    await this.#loadCurrent();
  }

  async prev() {
    if (!this.queue.length) {
      return;
    }
    this.index = this.index > 0 ? this.index - 1 : 0;
    await this.#loadCurrent();
  }

  async toggle() {
    if (this.state === "stopped" && this.queue.length) {
      if (this.index < 0) {
        this.index = 0;
      }
      await this.#loadCurrent();
      return;
    }
    const paused = this.state !== "playing";
    await this.mpv.pause(!paused ? true : false);
    this.state = paused ? "playing" : "paused";
  }

  async play() {
    if (this.state === "stopped" && this.queue.length) {
      await this.#loadCurrent();
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
  }

  async stop() {
    await this.mpv.pause(true);
    this.state = "stopped";
  }

  async seek(seconds) {
    await this.mpv.seekAbsolute(seconds);
  }

  async volume(value) {
    await this.mpv.setVolume(value);
  }

  setShuffle(name) {
    if (name === "on") {
      this.shuffle = true;
    } else if (name === "off") {
      this.shuffle = false;
    } else {
      this.shuffle = !this.shuffle;
    }
  }

  setRepeat(name) {
    if (name === "cycle") {
      this.repeat = this.repeat === "off" ? "all" : this.repeat === "all" ? "one" : "off";
      return;
    }
    if (["off", "all", "one"].includes(name)) {
      this.repeat = name;
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
  }

  async setEqBand(index, value) {
    if (index < 0 || index > 9) {
      throw new Error("EQ band must be 0-9");
    }
    this.eqBands[index] = Number(value);
    this.eqPreset = "Custom";
    await this.applyEq();
  }

  async status() {
    let position = 0;
    let duration = 0;
    let volume = 70;
    let paused = true;
    try {
      position = (await this.mpv.get("time-pos")) || 0;
      duration = (await this.mpv.get("duration")) || 0;
      volume = await this.mpv.get("volume");
      paused = await this.mpv.get("pause");
    } catch {
      /* idle mpv */
    }
    if (this.state !== "stopped") {
      this.state = paused ? "paused" : "playing";
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
      eq_preset: this.eqPreset,
      eq_bands: [...this.eqBands],
    };
  }

  prefetchNext() {
    const next = this.queue[this.index + 1];
    if (!next?.id || this.cache.get(next.id)) {
      return;
    }
    this.#resolve(next.id).catch(() => {});
  }

  async #loadCurrent() {
    const track = this.queue[this.index];
    if (!track) {
      throw new Error("nothing to play");
    }
    const url = await this.#resolve(track.id);
    await this.mpv.load(url);
    await this.mpv.pause(false);
    this.state = "playing";
    this.prefetchNext();
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

function normalize(track) {
  return {
    id: track.id,
    title: track.title || track.id,
    artist: track.artist || "",
    album: track.album || "",
    duration_secs: Number(track.duration_secs || 0),
    path: track.path || `https://music.youtube.com/watch?v=${track.id}`,
  };
}
