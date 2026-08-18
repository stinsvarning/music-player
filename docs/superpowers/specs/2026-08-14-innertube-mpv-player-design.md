# Standalone YouTube Music player (Innertube + mpv)

Date: 2026-08-14

## Goal

A new standalone desktop player that looks like the compact GTK chrome we already built (QUEUE / EQUALIZER / MUSIC), but plays YouTube Music through **Innertube + mpv** so start and in-track seek feel like Pear Desktop, not like cliamp/yt-dlp.

Not a fork of cliamp. Not a patch on `cliamp-gui`. Not Electron.

## Locked decisions

- New project at `~/Projects/music-player`
- Same GTK look (mint/amber, 920×720 float, single-click browse, Enter / double-click play)
- YouTube Music only in v1 (no radio, no local files, no cliamp)
- Two processes: GTK UI + Node engine
- Engine uses `youtubei.js` + `bgutils-js` (same stack Pear already uses here) and **mpv** for audio
- Auth: cookies from this machine’s browser (config `cookies_from`, then saved `cookies.header`, then a scan of Zen / Firefox / Chrome / Brave / Edge / …) + poToken. No Google Cloud OAuth app.

## Why this engine

Pear works because it embeds the official YouTube Music web player. cliamp restarts `yt-dlp | ffmpeg` on every play and every seek.

This project keeps Pear’s *API* approach (Innertube signed audio URL) and drops Pear’s *window* (Chromium). mpv plays that URL with normal HTTP range seeks.

## Architecture

```
┌─────────────────────────────────────┐
│  ui/   GTK4 Python                  │
│  QUEUE · EQUALIZER · MUSIC          │
└─────────────────┬───────────────────┘
                  │ newline JSON
                  │ ~/.config/music-player/engine.sock
┌─────────────────▼───────────────────┐
│  engine/   Node                     │
│  Innertube (search, library, URL)   │
│  mpv --idle --no-video              │
│  ~/.config/music-player/mpv.sock    │
└─────────────────────────────────────┘
```

UI never talks to mpv or YouTube directly. Engine never draws a window.

The engine owns mpv and **outlives the GTK window**. Close / Super+W / Super+X hide the window and leave audio running. **Ctrl+Q** shuts down the engine and mpv. A second UI attaches to the live engine; it does not spawn a second mpv.

## Components

### Engine (Node, ESM)

Dependencies: `youtubei.js` (17.x), `bgutils-js`, `happy-dom` (poToken interpreter, as in Pear’s downloader).

On start:

1. Resolve cookies: explicit `cookies_from` in `config.toml`, else `cookies.header`, else scan known browsers (Zen, Firefox, LibreWolf, Chrome, Chromium, Brave, Edge, Vivaldi, Helium).
2. `Innertube.create` with that cookie header, `generate_session_locally: true`.
3. Generate a poToken via `bgutils-js` (same `requestKey` / visitorData flow Pear uses).
4. Spawn `mpv --idle=yes --no-video --force-window=no --audio-display=no --input-ipc-server=<mpv.sock>`.
5. Restore `session.json` (queue, playhead, transport flags, volume, EQ) without auto-playing.
6. Listen on `engine.sock` only if nothing already answers there (do not unlink a live socket).

Innertube surface (v1):

- `music.search(query)` → songs shelf
- `music.getLibrary()` → user playlists
- `music.getPlaylist(id)` → tracks
- `music.getInfo(videoId)` → pick best audio-only format: `AUDIO_QUALITY_HIGH` first, then bitrate (Premium High ≈ itag 774 Opus or 141 AAC 256; not “prefer 140”)

Prefetch: when a track starts, resolve the next queue item’s URL in the background. Click-to-sound should often skip the Innertube round trip.

URL cache: `~/.config/music-player/url-cache.json`, `videoId → { url, expiresAt }`. Expiry comes from the signed URL’s `expire=` (unix seconds). Do not reuse after that time.

### mpv

JSON IPC only.

| Need | mpv command |
|---|---|
| Play | `loadfile <url> replace` |
| Queue next | `loadfile <url> append` (optional; engine may replace per track) |
| Pause | `set_property pause yes/no` |
| Seek | `seek <seconds> absolute` |
| Volume | `set_property volume 0–100` |
| Position | `get_property time-pos` / `duration` |
| EQ | `af` lavfi equalizer, 10 Winamp-shaped bands + a preamp so peak boost ≤ 0 dB |
| Quit | `quit` |

v1 plays one file at a time (`replace`). When the current file ends, engine loads the next queue item (already prefetched if possible).

### Protocol (engine.sock)

Newline-delimited JSON. Same *shape* as cliamp IPC so the GTK client stays simple. **Seek is absolute seconds. Volume is 0–100.** Do not copy cliamp’s relative-seek / dB-volume mistakes.

Requests (v1):

```text
{"cmd":"status"}
{"cmd":"play"} | pause | toggle | stop | next | prev
{"cmd":"seek","value":90}                 # absolute seconds
{"cmd":"volume","value":70}               # 0–100
{"cmd":"shuffle","name":"on|off|toggle"}
{"cmd":"repeat","name":"off|all|one|cycle"}
{"cmd":"eq","name":"Warm"}              # Flat | Warm | Vocal | Bass | Night
{"cmd":"eq","band":0,"value":6}
{"cmd":"queue.list"}
{"cmd":"queue.play","index":2}
{"cmd":"track.play","track":{"id":"...","title":"...","artist":"...","duration_secs":200}}
{"cmd":"track.queue","track":{...}}
{"cmd":"search","query":"..."}          # first Songs shelf + done; then search.more
{"cmd":"playlists"}                     # first page + done; then playlists.more
{"cmd":"playlist.tracks","id":"..."}    # first page + done; then playlist.tracks.more
```

`status` includes `state`, `track`, `position`, `duration`, `volume`, `index`, `total`, `shuffle`, `repeat`, `automix`, `eq_preset`, `eq_bands`.

Session file `~/.config/music-player/session.json`: queue, index, position, shuffle, repeat, automix, volume, EQ, sleep deadline. Restore does not auto-play. An already-due sleep is dropped, not fired.

Errors: `{"ok":false,"error":"..."}` with a string the footer can show (cookie expired, stream forbidden, mpv died).

### GTK UI

New code under `ui/`, visually cloned from `cliamp-gui` (not imported as a package). Tabs: **QUEUE**, **EQUALIZER**, **MUSIC**. No RADIO.

Behavior already proven:

- Single-click selects / browses
- Enter or double-click plays
- Seek slider sends **one** command on release
- Transport on a background thread (never block GTK on Innertube)
- Close / Super+W hides the window and leaves the engine running
- Ctrl+Q / engine `shutdown` stops engine + mpv

Hyprland: float, center, 920×720, opaque, class `stream.music.Player`.

### Auth

Config `~/.config/music-player/config.toml`:

```toml
cookies_from = "auto"
# cookies_from = "firefox:~/.config/zen"
```

If cookies or poToken fail: do not crash the window. Show the sign-in overlay. Open YouTube Music in a browser on this computer, sign in, then click I've signed in. Saved header: `cookies.header` mode `600`.

No interactive OAuth in v1.

## Data flow

**Play a search hit**

1. UI `search` → engine `music.search` → song list (ids, titles, artists, durations).
2. User hits Enter on a row → `track.play`.
3. Engine `getInfo` (or cache) → audio URL → `mpv loadfile`.
4. Status poll shows position from mpv (not from yt-dlp).

**Play a playlist**

1. `playlists` → `playlist.tracks`.
2. Enter on playlist: replace queue, play index 0, prefetch 1.
3. Enter on a track: play that id, set queue to the playlist around it.

**Seek**

1. User releases slider at 90s.
2. Engine `seek 90 absolute` to mpv.
3. Position should move without tearing down the stream.

## Error handling

| Failure | Behavior |
|---|---|
| Innertube 403 / bot check | Refresh poToken once, retry `getInfo`. If still failing, surface the error. |
| Expired stream URL | Cache drops rows past `expire=`. If mpv fails to load a **cached** URL, drop that id, resolve once more, and load the new URL. |
| Stale cookies | Footer; do not loop retries. |
| mpv exits | Restart mpv, keep queue in engine memory, do not auto-resume until the user hits play. |
| Engine socket busy | One instance per user. Second UI attaches; it does not spawn a second mpv. |

## Success criteria (v1)

- Cold play (no cached URL): sound in **under 3 seconds** on this machine’s network.
- Warm play (prefetched URL): sound in **under 1.5 seconds**.
- Seek: audible new position in **under 200 ms**; no full stream restart.
- Combined RSS of UI + engine + mpv typically **under 200 MB** (well below Pear/Electron).
- Super+W / close window **leaves audio playing**; Ctrl+Q leaves no leftover engine/mpv.
- 10-band EQ is audible through mpv (Flat / Warm / Vocal / Bass / Night + preamp).

If Innertube + poToken cannot meet the cold-play bar after a honest try on this machine, stop and report; do not silently fall back to yt-dlp.

## Testing

- Engine unit tests: protocol parse, format pick (HIGH then bitrate), URL cache expiry (`expire=`), seek command is absolute, session restore.
- Engine integration (manual + script): spawn mpv with a short public HTTP file (not YouTube) and assert seek/pause. Then one live Innertube play behind a flag.
- UI: clone the existing gtk-less tests (models, seek gate, theme). No requirement to automate GTK clicks in v1.
- Close-path test: start engine+mpv, send shutdown, assert both pids gone.

## Out of scope (v1)

- Radio, local files, Spotify, cliamp
- Electron / Pear window
- Lyrics, scrobbling (MPRIS is implemented as `org.mpris.MediaPlayer2.Music`)
- Packaging for AUR
- Video

## Risks

- YouTube changes Innertube or poToken; Pear will feel it too. Engine should isolate that in one module.
- Cookie readers break when the browser has the sqlite DB locked; sign in again from the overlay, or set `cookies_from` at a profile that is not locked.
- This is unofficial, same class of tool as Pear’s Innertube downloader. No official YouTube Music branding.

## Project layout

```text
~/Projects/music-player/
  docs/superpowers/specs/   # this document
  engine/                   # Node
  ui/                       # Python GTK
  packaging/                # desktop entry, hypr rules
  README.md
```
