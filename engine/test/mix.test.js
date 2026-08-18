import assert from "node:assert/strict";
import { test } from "node:test";
import {
  chunkIds,
  collectAllTracks,
  continueSearchCollection,
  continueTrackCollection,
  extractSongs,
  panelSongs,
  songRadioId,
  startSearchCollection,
  startTrackCollection,
  uniqueAfter,
  uniqueVideoIds,
} from "../src/mix.js";

test("songRadioId builds a YouTube Music radio playlist id", () => {
  assert.equal(songRadioId("4neXNZyChkY"), "RDAMVM4neXNZyChkY");
  assert.equal(songRadioId("RDAMVMabc"), "RDAMVMabc");
  assert.equal(songRadioId(""), "");
});

test("panelSongs reads PlaylistPanel videos and wrappers", () => {
  const songs = panelSongs({
    contents: [
      { video_id: "aaa", title: "One", artists: [{ name: "A" }], duration: { seconds: 12 } },
      { primary: { video_id: "bbb", title: "Two", author: "B" } },
      { title: "not a video" },
    ],
  });
  assert.deepEqual(
    songs.map((t) => t.id),
    ["aaa", "bbb"],
  );
  assert.equal(songs[0].artist, "A");
  assert.equal(songs[1].artist, "B");
});

test("extractSongs skips continuation rows and non-songs", () => {
  const songs = extractSongs([
    { id: "aaa", item_type: "song", title: "One", artists: [{ name: "A" }], duration: { seconds: 12 } },
    { type: "ContinuationItem", id: "token" },
    { item_type: "playlist", id: "PL1", title: "not a song" },
    { video_id: "bbb", title: "Two", author: { name: "B" } },
  ]);
  assert.deepEqual(
    songs.map((t) => t.id),
    ["aaa", "bbb"],
  );
  assert.equal(songs[0].artist, "A");
});

test("collectAllTracks follows playlist continuations", async () => {
  const page2 = {
    items: [{ id: "c", item_type: "song", title: "Three" }],
    has_continuation: false,
  };
  const page1 = {
    contents: [
      { id: "a", item_type: "song", title: "One" },
      { id: "b", item_type: "song", title: "Two" },
    ],
    has_continuation: true,
    getContinuation: async () => page2,
  };
  const tracks = await collectAllTracks(page1);
  assert.deepEqual(
    tracks.map((t) => t.id),
    ["a", "b", "c"],
  );
});

function pagedPlaylist() {
  const page2 = {
    items: [{ id: "c", item_type: "song", title: "Three" }],
    has_continuation: false,
  };
  return {
    contents: [
      { id: "a", item_type: "song", title: "One" },
      { id: "b", item_type: "song", title: "Two" },
    ],
    has_continuation: true,
    getContinuation: async () => page2,
  };
}

test("startTrackCollection returns the first page only", async () => {
  const session = startTrackCollection(pagedPlaylist());
  assert.deepEqual(
    session.tracks.map((t) => t.id),
    ["a", "b"],
  );
  assert.equal(session.done, false);
});

test("continueTrackCollection yields the next page and marks done", async () => {
  const first = startTrackCollection(pagedPlaylist());
  const next = await continueTrackCollection(first);
  assert.deepEqual(
    next.tracks.map((t) => t.id),
    ["c"],
  );
  assert.equal(next.done, true);
});

function pagedSearch() {
  const page2 = {
    contents: [{ id: "c", item_type: "song", title: "Three" }],
    has_continuation: false,
  };
  return {
    songs: {
      contents: [
        { id: "a", item_type: "song", title: "One" },
        { id: "b", item_type: "song", title: "Two" },
      ],
    },
    contents: [{ item_type: "playlist", id: "PL1", title: "not the songs shelf" }],
    has_continuation: true,
    getContinuation: async () => page2,
  };
}

test("startSearchCollection uses the Songs shelf on the first page only", () => {
  const session = startSearchCollection(pagedSearch());
  assert.deepEqual(
    session.tracks.map((t) => t.id),
    ["a", "b"],
  );
  assert.equal(session.done, false);
});

test("continueSearchCollection yields the next search page and marks done", async () => {
  const first = startSearchCollection(pagedSearch());
  const next = await continueSearchCollection(first);
  assert.deepEqual(
    next.tracks.map((t) => t.id),
    ["c"],
  );
  assert.equal(next.done, true);
});

test("uniqueAfter drops ids already in the queue", () => {
  const extra = uniqueAfter(
    [
      { id: "a", title: "A" },
      { id: "c", title: "C" },
      { id: "c", title: "dup" },
    ],
    ["a", "b"],
  );
  assert.deepEqual(
    extra.map((t) => t.id),
    ["c"],
  );
});

test("uniqueVideoIds keeps first-seen queue order", () => {
  assert.deepEqual(
    uniqueVideoIds([{ id: "a" }, { id: "" }, { id: "b" }, { id: "a" }, "c", ""]),
    ["a", "b", "c"],
  );
});

test("chunkIds splits ids for playlist edits", () => {
  assert.deepEqual(chunkIds(["a", "b", "c", "d"], 2), [
    ["a", "b"],
    ["c", "d"],
  ]);
  assert.deepEqual(chunkIds([], 50), []);
});
