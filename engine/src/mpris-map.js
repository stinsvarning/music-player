export function playbackStatus(state) {
  if (state === "playing") {
    return "Playing";
  }
  if (state === "paused") {
    return "Paused";
  }
  return "Stopped";
}

export function loopStatus(repeat) {
  if (repeat === "one") {
    return "Track";
  }
  if (repeat === "all") {
    return "Playlist";
  }
  return "None";
}

export function mprisVolume(volume) {
  const n = Number(volume);
  if (!Number.isFinite(n)) {
    return 0;
  }
  return Math.max(0, Math.min(1, n / 100));
}

export function metadataFromStatus(status) {
  const track = status?.track || {};
  const id = String(track.id || "none").replace(/[^A-Za-z0-9_]/g, "_");
  const length = Math.max(0, Math.round(Number(status?.duration || track.duration_secs || 0) * 1_000_000));
  const art = track.id ? `https://i.ytimg.com/vi/${track.id}/hqdefault.jpg` : "";
  return {
    "mpris:trackid": `/org/mpris/MediaPlayer2/track/${id}`,
    "mpris:length": length,
    "mpris:artUrl": art,
    "xesam:title": track.title || "Nothing playing",
    "xesam:artist": [track.artist || ""],
    "xesam:album": track.album || "",
    "xesam:url": track.path || "",
  };
}

export function statusSignature(status) {
  const track = status?.track || {};
  return [
    status?.state,
    status?.shuffle,
    status?.repeat,
    Math.round(Number(status?.volume || 0)),
    track.id,
    track.title,
    Math.round(Number(status?.duration || 0)),
  ].join("|");
}
