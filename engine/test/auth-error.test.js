import assert from "node:assert/strict";
import { test } from "node:test";
import { AUTH_REFRESH_MS, looksLikeAuthError } from "../src/auth-error.js";
import { Youtube } from "../src/youtube.js";

test("looksLikeAuthError matches login and 401", () => {
  assert.equal(looksLikeAuthError("LOGIN_REQUIRED: expired"), true);
  assert.equal(looksLikeAuthError(new Error("Request failed with status code 401")), true);
  assert.equal(looksLikeAuthError("unauthenticated"), true);
  assert.equal(looksLikeAuthError("status code 400"), false);
  assert.equal(looksLikeAuthError("playlist is empty"), false);
});

test("auth refresh interval is fifteen minutes", () => {
  assert.equal(AUTH_REFRESH_MS, 15 * 60 * 1000);
});

test("playlists retries once after an auth error", async () => {
  let calls = 0;
  let expired = 0;
  const youtube = new Youtube();
  youtube.loggedIn = true;
  youtube.yt = {
    music: {
      getLibrary: async () => {
        calls += 1;
        if (calls === 1) {
          throw new Error("LOGIN_REQUIRED: cookie expired");
        }
        return { contents: [], filters: [] };
      },
    },
  };
  youtube.onAuthExpired = async () => {
    expired += 1;
  };
  const page = await youtube.playlists();
  assert.equal(calls, 2);
  assert.equal(expired, 1);
  assert.equal(page.done, true);
  assert.deepEqual(page.playlists, []);
});
