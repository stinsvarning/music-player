export class UrlCache {
  constructor(ttlMs = 5 * 60 * 60 * 1000, now = () => Date.now()) {
    this.ttlMs = ttlMs;
    this.now = now;
    this.map = new Map();
  }

  get(videoId) {
    const row = this.map.get(videoId);
    if (!row) {
      return null;
    }
    if (this.now() >= row.expiresAt) {
      this.map.delete(videoId);
      return null;
    }
    return row.url;
  }

  set(videoId, url) {
    this.map.set(videoId, { url, expiresAt: this.now() + this.ttlMs });
  }

  drop(videoId) {
    this.map.delete(videoId);
  }
}
