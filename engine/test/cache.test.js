import assert from "node:assert/strict";
import { test } from "node:test";
import { UrlCache } from "../src/cache.js";

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
