import assert from "node:assert/strict";
import { test } from "node:test";
import {
  collectAllPlaylists,
  continuePlaylistCollection,
  dedupePlaylists,
  extractPlaylists,
  deletePlaylistRequest,
  playlistIsEditable,
  renamePlaylistRequest,
  startPlaylistCollection,
} from "../src/library.js";

test("renamePlaylistRequest posts edit_playlist with playlistId", async () => {
  const calls = [];
  const result = await renamePlaylistRequest({
    execute: async (endpoint, body) => {
      calls.push([endpoint, body]);
      return { success: true, status_code: 200 };
    },
    playlistId: "VLPL123",
    name: "333",
  });
  assert.deepEqual(calls, [
    [
      "/browse/edit_playlist",
      {
        playlistId: "PL123",
        actions: [{ action: "ACTION_SET_PLAYLIST_NAME", playlistName: "333" }],
        client: "YTMUSIC",
      },
    ],
  ]);
  assert.deepEqual(result, { playlist_id: "PL123", name: "333" });
});

test("renamePlaylistRequest rejects a 400", async () => {
  await assert.rejects(
    () =>
      renamePlaylistRequest({
        execute: async () => ({ success: false, status_code: 400 }),
        playlistId: "PL123",
        name: "333",
      }),
    /could not rename/,
  );
});

test("deletePlaylistRequest posts playlist/delete with playlistId", async () => {
  const calls = [];
  const result = await deletePlaylistRequest({
    execute: async (endpoint, body) => {
      calls.push([endpoint, body]);
      return { success: true, status_code: 200 };
    },
    playlistId: "VLPL123",
  });
  assert.deepEqual(calls, [
    ["/playlist/delete", { playlistId: "PL123", client: "YTMUSIC" }],
  ]);
  assert.deepEqual(result, { playlist_id: "PL123" });
});

test("deletePlaylistRequest rejects a 400", async () => {
  await assert.rejects(
    () =>
      deletePlaylistRequest({
        execute: async () => ({ success: false, status_code: 400 }),
        playlistId: "PL123",
      }),
    /could not delete/,
  );
});

test("playlistIsEditable is only true for user playlists", () => {
  assert.equal(playlistIsEditable("PL123"), true);
  assert.equal(playlistIsEditable("VLPL123"), true);
  assert.equal(playlistIsEditable("LM"), false);
  assert.equal(playlistIsEditable("VLLM"), false);
  assert.equal(playlistIsEditable("RDAMPLPL123"), false);
  assert.equal(playlistIsEditable("OLAK5uy_abc"), false);
  assert.equal(playlistIsEditable(""), false);
});

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
