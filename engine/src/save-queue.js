import { chunkIds, uniqueVideoIds } from "./mix.js";
import { playlistEditId, textOf } from "./text.js";

export async function saveQueue({ create, addVideos, title, playlistId, videoIds }) {
  const ids = uniqueVideoIds(videoIds);
  if (!ids.length) {
    throw new Error("queue is empty");
  }
  if (playlistId) {
    const id = playlistEditId(playlistId);
    if (!id) {
      throw new Error("playlist id is required");
    }
    for (const batch of chunkIds(ids)) {
      await addVideos(id, batch);
    }
    return { playlist_id: id, created: false, total: ids.length };
  }
  const name = textOf(title).trim();
  if (!name) {
    throw new Error("playlist name is required");
  }
  if (typeof create !== "function" || typeof addVideos !== "function") {
    throw new Error("playlist save is not available");
  }
  const [first, ...rest] = ids;
  const created = await create(name, [first]);
  const id = playlistEditId(created?.playlist_id);
  if (!id) {
    throw new Error("YouTube did not return a playlist id");
  }
  for (const batch of chunkIds(rest)) {
    await addVideos(id, batch);
  }
  return { playlist_id: id, name, created: true, total: ids.length };
}
