function arg(name, type, required = false) {
  return { name, type, required };
}

export const COMMANDS = [
  { cmd: "help", risk: "read", args: [], summary: "List every engine command, arguments, and risk tag" },
  { cmd: "commands", risk: "read", args: [], summary: "Alias for help" },
  { cmd: "status", risk: "read", args: [], summary: "Now playing, position, volume, EQ, sleep" },
  { cmd: "bands", risk: "read", args: [], summary: "In-memory spectrum bands" },
  { cmd: "auth.status", risk: "read", args: [], summary: "Whether a YouTube Music session is logged in" },
  { cmd: "auth.refresh", risk: "dangerous", args: [arg("skip_saved", "boolean"), arg("cookies_from", "string")], summary: "Re-scan browsers and replace the saved cookie header" },
  { cmd: "auth.logout", risk: "write", args: [], summary: "Forget the saved Google session and sign out" },
  { cmd: "play", risk: "write", args: [], summary: "Resume or start the current queue item" },
  { cmd: "pause", risk: "write", args: [], summary: "Pause playback" },
  { cmd: "toggle", risk: "write", args: [], summary: "Play if paused, pause if playing" },
  { cmd: "stop", risk: "write", args: [], summary: "Stop; keep the queue and playhead" },
  { cmd: "next", risk: "write", args: [], summary: "Next track" },
  { cmd: "prev", risk: "write", args: [], summary: "Previous track" },
  { cmd: "seek", risk: "write", args: [arg("value", "number", true)], summary: "Seek to an absolute position in seconds" },
  { cmd: "volume", risk: "write", args: [arg("value", "number", true)], summary: "Set volume 0–100" },
  { cmd: "shuffle", risk: "write", args: [arg("name", "string")], summary: "Shuffle on, off, or toggle" },
  { cmd: "repeat", risk: "write", args: [arg("name", "string")], summary: "Repeat off, all, one, or cycle" },
  { cmd: "automix", risk: "write", args: [arg("name", "string")], summary: "Play similar on, off, or toggle" },
  { cmd: "eq", risk: "write", args: [arg("name", "string"), arg("band", "number"), arg("value", "number")], summary: "EQ preset Flat/Warm/Vocal/Bass/Night or one band" },
  { cmd: "sleep", risk: "write", args: [arg("minutes", "number")], summary: "Sleep timer in minutes; 0 clears it" },
  { cmd: "queue.list", risk: "read", args: [], summary: "Queue tracks and current index" },
  { cmd: "queue.play", risk: "write", args: [arg("index", "number", true)], summary: "Play a queue index" },
  { cmd: "queue.move", risk: "write", args: [arg("from", "number", true), arg("to", "number", true)], summary: "Reorder the queue" },
  { cmd: "queue.remove", risk: "write", args: [arg("index", "number", true)], summary: "Remove a queue row" },
  {
    cmd: "queue.save",
    risk: "write",
    args: [arg("name", "string"), arg("playlist_id", "string")],
    summary: "Save the queue as a new playlist (name) or append to playlist_id",
  },
  { cmd: "track.play", risk: "write", args: [arg("track", "object", true), arg("replace", "boolean")], summary: "Play a track; replace the queue unless replace is false. Does not start a mix" },
  { cmd: "track.queue", risk: "write", args: [arg("track", "object", true)], summary: "Append a track to the queue" },
  { cmd: "track.play_next", risk: "write", args: [arg("track", "object", true)], summary: "Insert a track after the current item" },
  { cmd: "track.mix", risk: "write", args: [arg("track", "object", true)], summary: "Replace the queue with a radio mix from this track" },
  { cmd: "track.liked", risk: "read", args: [arg("id", "string"), arg("track", "object")], summary: "Whether this video is liked or in Liked Music" },
  { cmd: "track.like", risk: "write", args: [arg("id", "string"), arg("track", "object")], summary: "Like a track and add it to Liked Music" },
  { cmd: "track.unlike", risk: "write", args: [arg("id", "string"), arg("track", "object")], summary: "Remove a like or dislike from a track" },
  { cmd: "track.dislike", risk: "write", args: [arg("id", "string"), arg("track", "object")], summary: "Dislike a track" },
  { cmd: "search", risk: "read", args: [arg("query", "string", true)], summary: "Search songs; first page plus done" },
  { cmd: "search.more", risk: "read", args: [arg("query", "string")], summary: "Next search page" },
  { cmd: "playlists", risk: "read", args: [], summary: "Library playlists; first page plus done" },
  { cmd: "playlists.more", risk: "read", args: [], summary: "Next playlist page" },
  { cmd: "playlist.tracks", risk: "read", args: [arg("id", "string", true)], summary: "Playlist tracks; first page plus done. Does not change the queue" },
  { cmd: "playlist.tracks.more", risk: "read", args: [arg("id", "string")], summary: "Next playlist track page" },
  { cmd: "playlist.play", risk: "write", args: [arg("id", "string", true), arg("index", "number")], summary: "Load a whole playlist into the queue and play" },
  { cmd: "playlist.add", risk: "write", args: [arg("playlist_id", "string", true), arg("video_id", "string", true)], summary: "Add one video to a playlist" },
  { cmd: "playlist.rename", risk: "write", args: [arg("id", "string", true), arg("name", "string", true)], summary: "Rename a playlist you own" },
  { cmd: "playlist.delete", risk: "write", args: [arg("id", "string", true)], summary: "Delete a playlist you own" },
  { cmd: "playlist.mix", risk: "write", args: [arg("id", "string", true)], summary: "Replace the queue with a radio mix from this playlist" },
  { cmd: "lyrics", risk: "read", args: [arg("id", "string")], summary: "Plain lyrics for a video id, or the current track" },
  { cmd: "shutdown", risk: "dangerous", args: [], summary: "Quit the engine and mpv" },
];

export function commandCatalog() {
  return COMMANDS.map((row) => ({
    cmd: row.cmd,
    risk: row.risk,
    args: row.args.map((a) => ({ ...a })),
    summary: row.summary,
  }));
}

export function commandRisk(cmd) {
  return COMMANDS.find((row) => row.cmd === cmd)?.risk || null;
}
