import assert from "node:assert/strict";
import { test } from "node:test";
import {
  collectAllPlaylists,
  continuePlaylistCollection,
  dedupePlaylists,
  extractPlaylists,
  startPlaylistCollection,
} from "../src/library.js";

test("extractPlaylists walks a grid and maps ids", () => {
  const found = extractPlaylists({
    contents: [
      {
        type: "Grid",
        contents: [
          { item_type: "playlist", id: "VLLM", title: "Liked Music", item_count: "12" },
          { item_type: "song", id: "abc", title: "not a playlist" },
          { playlist_id: "PL123", title: { text: "Mine" }, song_count: 4 },
        ],
      },
    ],
  });
  assert.deepEqual(
    found.map((p) => p.id),
    ["VLLM", "PL123"],
  );
  assert.equal(found[0].name, "Liked Music");
  assert.equal(found[1].track_count, 4);
});

test("dedupePlaylists keeps the first copy of each id", () => {
  const found = dedupePlaylists([
    { id: "VLLM", name: "Liked Music", track_count: 1 },
    { id: "PL1", name: "One", track_count: 2 },
    { id: "VLLM", name: "Liked Music again", track_count: 9 },
  ]);
  assert.deepEqual(
    found.map((p) => p.id),
    ["VLLM", "PL1"],
  );
  assert.equal(found[0].track_count, 1);
});

test("collectAllPlaylists applies Playlists filter and follows continuation", async () => {
  const page2 = {
    contents: [{ item_type: "playlist", id: "PL2", title: "Two" }],
    has_continuation: false,
  };
  const filtered = {
    contents: [{ item_type: "playlist", id: "PL1", title: "One" }],
    has_continuation: true,
    getContinuation: async () => page2,
  };
  const landing = {
    filters: ["Songs", "Playlists"],
    contents: [{ item_type: "playlist", id: "PL1", title: "Preview" }],
    has_continuation: false,
    applyFilter: async (name) => {
      assert.equal(name, "Playlists");
      return filtered;
    },
  };
  const found = await collectAllPlaylists(landing);
  assert.deepEqual(
    found.map((p) => p.id),
    ["PL1", "PL2"],
  );
});

test("extractPlaylists plus dedupe removes a repeated shelf", () => {
  const shelf = [
    { item_type: "playlist", id: "PL1", title: "A" },
    { item_type: "playlist", id: "PL2", title: "B" },
  ];
  const found = dedupePlaylists(extractPlaylists({ contents: [{ contents: shelf }, { items: shelf }] }));
  assert.deepEqual(
    found.map((p) => p.id),
    ["PL1", "PL2"],
  );
});

function pagedLibrary() {
  const page2 = {
    contents: [{ item_type: "playlist", id: "PL2", title: "Two" }],
    has_continuation: false,
  };
  const filtered = {
    contents: [{ item_type: "playlist", id: "PL1", title: "One" }],
    has_continuation: true,
    getContinuation: async () => page2,
  };
  return {
    filters: ["Songs", "Playlists"],
    contents: [{ item_type: "playlist", id: "PL1", title: "Preview" }],
    has_continuation: false,
    applyFilter: async (name) => {
      assert.equal(name, "Playlists");
      return filtered;
    },
  };
}

test("startPlaylistCollection returns the first filtered page only", async () => {
  const session = await startPlaylistCollection(pagedLibrary());
  assert.deepEqual(
    session.playlists.map((p) => p.id),
    ["PL1"],
  );
  assert.equal(session.done, false);
});

test("continuePlaylistCollection yields the next page and marks done", async () => {
  const first = await startPlaylistCollection(pagedLibrary());
  const next = await continuePlaylistCollection(first);
  assert.deepEqual(
    next.playlists.map((p) => p.id),
    ["PL2"],
  );
  assert.equal(next.done, true);
});
