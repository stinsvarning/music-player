import { itemLooksUnplayable } from "./playable.js";
import { textOf } from "./text.js";

export function songRadioId(videoId) {
  const id = String(videoId || "").trim();
  if (!id) {
    return "";
  }
  if (id.startsWith("RD")) {
    return id;
  }
  return `RDAMVM${id}`;
}

export function panelSongs(panel, limit = 50) {
  const raw = panel?.contents || panel?.items || panel || [];
  const arr = Array.isArray(raw) ? raw : typeof raw[Symbol.iterator] === "function" ? [...raw] : [];
  const songs = [];
  for (const it of arr) {
    if (songs.length >= limit) {
      break;
    }
    const video = it?.video_id || it?.id ? it : it?.primary || it?.video || null;
    const id = textOf(video?.video_id || video?.id);
    if (!id) {
      continue;
    }
    songs.push({
      id,
      title: textOf(video.title) || textOf(video.name) || id,
      artist: textOf(video.artists?.[0]?.name) || textOf(video.author) || "",
      album: textOf(video.album?.name) || "",
      duration_secs: video.duration?.seconds || 0,
      playable: !itemLooksUnplayable(video),
    });
  }
  return songs;
}

function parseCount(text) {
  if (!text) {
    return 0;
  }
  const n = parseInt(String(text).replace(/[^\d]/g, ""), 10);
  return Number.isFinite(n) ? n : 0;
}

export function extractSongs(nodes, out = []) {
  const walk = (list) => {
    if (!list) {
      return;
    }
    const arr = Array.isArray(list)
      ? list
      : typeof list[Symbol.iterator] === "function"
        ? [...list]
        : list.contents || list.items || [];
    for (const it of arr) {
      if (!it || it.type === "ContinuationItem") {
        continue;
      }
      const id = textOf(it.id || it.video_id);
      const type = it.item_type;
      if (id && (!type || type === "song" || type === "video")) {
        out.push({
          id,
          title: textOf(it.title) || textOf(it.name) || id,
          artist: textOf(it.artists?.[0]?.name) || textOf(it.author?.name) || textOf(it.author) || "",
          album: textOf(it.album?.name) || textOf(it.album) || "",
          duration_secs: it.duration?.seconds || parseCount(it.duration) || 0,
          playable: !itemLooksUnplayable(it),
        });
      }
      if (it.contents) {
        walk(it.contents);
      }
      if (it.items) {
        walk(it.items);
      }
    }
  };
  walk(nodes);
  return out;
}

function collectionDone(page) {
  return !page?.has_continuation || typeof page.getContinuation !== "function";
}

function songsOn(page) {
  return extractSongs(page?.videos || page?.items || page?.contents);
}

export function startTrackCollection(playlist) {
  const tracks = uniqueAfter(songsOn(playlist), []);
  return {
    tracks,
    page: playlist,
    seen: new Set(tracks.map((t) => t.id)),
    done: collectionDone(playlist),
  };
}

export async function continueTrackCollection(session) {
  if (!session || session.done) {
    return { tracks: [], page: session?.page, seen: session?.seen || new Set(), done: true };
  }
  const page = await session.page.getContinuation();
  const found = songsOn(page);
  const tracks = [];
  const seen = session.seen || new Set();
  for (const track of found) {
    if (!track?.id || seen.has(track.id)) {
      continue;
    }
    seen.add(track.id);
    tracks.push(track);
  }
  return {
    tracks,
    page,
    seen,
    done: collectionDone(page),
  };
}

function searchSongsOn(page) {
  return extractSongs(page?.songs?.contents || page?.videos || page?.items || page?.contents);
}

export function startSearchCollection(result) {
  const tracks = uniqueAfter(searchSongsOn(result), []);
  return {
    tracks,
    page: result,
    seen: new Set(tracks.map((t) => t.id)),
    done: collectionDone(result),
  };
}

export async function continueSearchCollection(session) {
  if (!session || session.done) {
    return { tracks: [], page: session?.page, seen: session?.seen || new Set(), done: true };
  }
  const page = await session.page.getContinuation();
  const found = searchSongsOn(page);
  const tracks = [];
  const seen = session.seen || new Set();
  for (const track of found) {
    if (!track?.id || seen.has(track.id)) {
      continue;
    }
    seen.add(track.id);
    tracks.push(track);
  }
  return {
    tracks,
    page,
    seen,
    done: collectionDone(page),
  };
}

export async function collectAllTracks(playlist) {
  let session = startTrackCollection(playlist);
  const found = [...session.tracks];
  let guard = 0;
  while (!session.done && guard < 50) {
    session = await continueTrackCollection(session);
    guard += 1;
    found.push(...session.tracks);
  }
  return found;
}

export function uniqueAfter(tracks, excludeIds) {
  const skip = new Set(excludeIds);
  const out = [];
  for (const track of tracks) {
    if (!track?.id || skip.has(track.id)) {
      continue;
    }
    skip.add(track.id);
    out.push(track);
  }
  return out;
}

export function uniqueVideoIds(items) {
  const seen = new Set();
  const out = [];
  for (const item of items || []) {
    const id = typeof item === "string" ? item.trim() : String(item?.id || "").trim();
    if (!id || seen.has(id)) {
      continue;
    }
    seen.add(id);
    out.push(id);
  }
  return out;
}

export function chunkIds(ids, size = 50) {
  const list = Array.isArray(ids) ? ids : [];
  const n = Math.max(1, Number(size) || 50);
  const out = [];
  for (let i = 0; i < list.length; i += n) {
    out.push(list.slice(i, i + n));
  }
  return out;
}
