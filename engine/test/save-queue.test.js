import assert from "node:assert/strict";
import { test } from "node:test";
import { saveQueue } from "../src/save-queue.js";

test("saveQueue creates a playlist from the first id and appends the rest", async () => {
  const created = [];
  const added = [];
  const result = await saveQueue({
    title: "  Night drive  ",
    videoIds: [{ id: "a" }, { id: "b" }, "a", "c"],
    create: async (title, ids) => {
      created.push({ title, ids });
      return { playlist_id: "VLPLnew" };
    },
    addVideos: async (playlistId, ids) => {
      added.push({ playlistId, ids });
    },
  });
  assert.deepEqual(created, [{ title: "Night drive", ids: ["a"] }]);
  assert.deepEqual(added, [{ playlistId: "PLnew", ids: ["b", "c"] }]);
  assert.deepEqual(result, { playlist_id: "PLnew", name: "Night drive", created: true, total: 3 });
});

test("saveQueue appends every id to an existing playlist", async () => {
  const added = [];
  const result = await saveQueue({
    playlistId: "VLPL123",
    videoIds: ["x", "y"],
    create: async () => {
      throw new Error("should not create");
    },
    addVideos: async (playlistId, ids) => {
      added.push({ playlistId, ids });
    },
  });
  assert.deepEqual(added, [{ playlistId: "PL123", ids: ["x", "y"] }]);
  assert.equal(result.created, false);
  assert.equal(result.playlist_id, "PL123");
  assert.equal(result.total, 2);
});

test("saveQueue rejects an empty queue and a missing name", async () => {
  await assert.rejects(
    () => saveQueue({ title: "x", videoIds: [], create: async () => ({}), addVideos: async () => {} }),
    /empty/,
  );
  await assert.rejects(
    () => saveQueue({ title: "  ", videoIds: ["a"], create: async () => ({}), addVideos: async () => {} }),
    /name/,
  );
});
