import assert from "node:assert/strict";
import { test } from "node:test";
import { likeStatusFromInfo, mergeLikeStatus, rateTrack } from "../src/like.js";

test("likeStatusFromInfo reads basic_info flags", () => {
  assert.deepEqual(likeStatusFromInfo({ basic_info: { is_liked: true } }), {
    liked: true,
    disliked: false,
  });
  assert.deepEqual(likeStatusFromInfo({ basic_info: { is_disliked: true } }), {
    liked: false,
    disliked: true,
  });
  assert.deepEqual(likeStatusFromInfo({ basic_info: { like_status: "INDIFFERENT" } }), {
    liked: false,
    disliked: false,
  });
  assert.deepEqual(likeStatusFromInfo({}), { liked: null, disliked: null });
});

test("mergeLikeStatus treats Liked Music membership as liked", () => {
  assert.deepEqual(
    mergeLikeStatus("aaa", new Set(["aaa", "bbb"]), { liked: false, disliked: false }),
    { liked: true, disliked: false },
  );
  assert.deepEqual(
    mergeLikeStatus("zzz", new Set(["aaa"]), { liked: false, disliked: true }),
    { liked: false, disliked: true },
  );
  assert.deepEqual(mergeLikeStatus("aaa", null, { liked: null, disliked: null }), {
    liked: null,
    disliked: null,
  });
});

test("rateTrack posts like/like with a videoId target", async () => {
  const calls = [];
  const result = await rateTrack({
    execute: async (endpoint, body) => {
      calls.push([endpoint, body]);
      return { success: true, status_code: 200 };
    },
    videoId: "abc",
    liked: true,
  });
  assert.deepEqual(calls, [
    ["/like/like", { target: { videoId: "abc" }, client: "YTMUSIC" }],
  ]);
  assert.deepEqual(result, { id: "abc", liked: true, disliked: false });
});

test("rateTrack unlikes through removelike and rejects a 400", async () => {
  const result = await rateTrack({
    execute: async () => ({ success: true, status_code: 200 }),
    videoId: "abc",
    liked: false,
  });
  assert.equal(result.liked, false);
  await assert.rejects(
    () =>
      rateTrack({
        execute: async () => ({ success: false, status_code: 400 }),
        videoId: "abc",
        liked: true,
      }),
    /could not like/,
  );
});
