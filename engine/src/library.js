import { textOf } from "./text.js";

function parseCount(text) {
  if (!text) {
    return 0;
  }
  const n = parseInt(String(text).replace(/[^\d]/g, ""), 10);
  return Number.isFinite(n) ? n : 0;
}

export function playlistIdOf(item) {
  return textOf(item?.id || item?.playlist_id);
}

export function isPlaylistItem(item) {
  if (!item) {
    return false;
  }
  if (item.item_type === "playlist") {
    return true;
  }
  if (item.playlist_id) {
    return true;
  }
  const id = String(item.id || "");
  return id.startsWith("PL") || id.startsWith("VL") || id === "LM";
}

export function toPlaylist(item) {
  const id = playlistIdOf(item);
  if (!id) {
    return null;
  }
  return {
    id,
    name: textOf(item.title) || textOf(item.name) || "playlist",
    track_count: parseCount(item.item_count || item.song_count),
  };
}

export function extractPlaylists(node, out = []) {
  if (!node) {
    return out;
  }
  if (Array.isArray(node)) {
    for (const child of node) {
      extractPlaylists(child, out);
    }
    return out;
  }
  if (isPlaylistItem(node)) {
    const playlist = toPlaylist(node);
    if (playlist) {
      out.push(playlist);
    }
  }
  if (node.contents) {
    extractPlaylists(node.contents, out);
  }
  if (node.items) {
    extractPlaylists(node.items, out);
  }
  return out;
}

export function dedupePlaylists(list) {
  const seen = new Set();
  const out = [];
  for (const playlist of list) {
    if (!playlist?.id || seen.has(playlist.id)) {
      continue;
    }
    seen.add(playlist.id);
    out.push(playlist);
  }
  return out;
}

function collectionDone(page) {
  return !page?.has_continuation || typeof page.getContinuation !== "function";
}

export async function startPlaylistCollection(library) {
  let page = library;
  const filters = page.filters || [];
  const playlistChip = filters.find((name) => /playlist/i.test(String(name)));
  if (playlistChip && typeof page.applyFilter === "function") {
    page = await page.applyFilter(playlistChip);
  }
  const playlists = dedupePlaylists(extractPlaylists(page.contents));
  return {
    playlists,
    page,
    seen: new Set(playlists.map((p) => p.id)),
    done: collectionDone(page),
  };
}

export async function continuePlaylistCollection(session) {
  if (!session || session.done) {
    return { playlists: [], page: session?.page, seen: session?.seen || new Set(), done: true };
  }
  const page = await session.page.getContinuation();
  const found = extractPlaylists(page.contents);
  const playlists = [];
  const seen = session.seen || new Set();
  for (const playlist of found) {
    if (!playlist?.id || seen.has(playlist.id)) {
      continue;
    }
    seen.add(playlist.id);
    playlists.push(playlist);
  }
  return {
    playlists,
    page,
    seen,
    done: collectionDone(page),
  };
}

export async function collectAllPlaylists(library) {
  let session = await startPlaylistCollection(library);
  const found = [...session.playlists];
  let guard = 0;
  while (!session.done && guard < 30) {
    session = await continuePlaylistCollection(session);
    guard += 1;
    found.push(...session.playlists);
  }
  return found;
}
