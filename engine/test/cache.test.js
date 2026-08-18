import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { UrlCache, parseExpireAt } from "../src/cache.js";

test("returns stored url before expiry", () => {
  let now = 1000;
  const cache = new UrlCache(5000, () => now);
  cache.set("abc", "https://example/a");
  assert.equal(cache.get("abc"), "https://example/a");
});

test("expires urls", () => {
  let now = 1000;
  const cache = new UrlCache(5000, () => now);
  cache.set("abc", "https://example/a");
  now = 7000;
  assert.equal(cache.get("abc"), null);
});

test("parseExpireAt reads unix seconds from expire=", () => {
  assert.equal(parseExpireAt("https://rr.googlevideo.com/videoplayback?id=x&expire=1700000000"), 1700000000 * 1000);
  assert.equal(parseExpireAt("https://rr.googlevideo.com/videoplayback?expires=1700000000000"), 1700000000000);
  assert.equal(parseExpireAt("https://example/a"), null);
});

test("set uses expire= instead of the default ttl", () => {
  let now = 1_700_000_000_000;
  const cache = new UrlCache(5000, () => now);
  cache.set("abc", "https://rr.example/videoplayback?expire=1700003600");
  now = 1_700_000_000_000 + 4000;
  assert.ok(cache.get("abc"));
  now = 1_700_003_600_000;
  assert.equal(cache.get("abc"), null);
});

test("disk cache reloads unexpired urls", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "music-urlcache-"));
  const file = path.join(dir, "urls.json");
  let now = 1_700_000_000_000;
  const first = new UrlCache({ ttlMs: 5000, now: () => now, filePath: file });
  first.set("abc", "https://rr.example/videoplayback?expire=1700003600");
  first.flush();
  const second = new UrlCache({ ttlMs: 5000, now: () => now, filePath: file });
  assert.match(second.get("abc"), /expire=1700003600/);
  now = 1_700_003_600_000;
  assert.equal(second.get("abc"), null);
});

test("disk cache skips expired rows on load", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "music-urlcache-"));
  const file = path.join(dir, "urls.json");
  fs.writeFileSync(
    file,
    JSON.stringify({
      version: 1,
      entries: {
        old: { url: "https://rr.example/videoplayback?expire=1", expiresAt: 1000 },
        live: { url: "https://rr.example/videoplayback?expire=9999", expiresAt: 9_999_999_999_000 },
      },
    }),
  );
  const cache = new UrlCache({ now: () => 2_000, filePath: file });
  assert.equal(cache.get("old"), null);
  assert.match(cache.get("live"), /expire=9999/);
});
