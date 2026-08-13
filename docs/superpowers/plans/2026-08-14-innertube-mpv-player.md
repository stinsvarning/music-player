# Innertube + mpv player Implementation Plan

> **For agentic workers:** Execute inline in this session. Engine first, then GTK. Do not fall back to yt-dlp for audio.

**Goal:** Standalone GTK YouTube Music player that starts and seeks via Innertube + mpv.

**Architecture:** Node engine owns Innertube and mpv. Python GTK talks newline JSON on `~/.config/music-player/engine.sock`. Seek is absolute seconds. Volume is 0–100.

**Tech Stack:** Node 22+, youtubei.js 17, bgutils-js, happy-dom, mpv 0.41, Python 3.14 + GTK4 (`/usr/bin/python3`).

## Global Constraints

- Project root: `/home/llurd/Projects/music-player`
- YouTube Music only in v1
- No Electron, no cliamp, no yt-dlp playback
- Cookies: `firefox:~/.config/zen` plus poToken
- Close window / SIGTERM must kill engine and mpv
- Cold play < 3s, warm < 1.5s, seek < 200ms

## Files

```
engine/package.json
engine/src/paths.js
engine/src/formats.js
engine/src/cache.js
engine/src/eq.js
engine/src/protocol.js
engine/src/mpv.js
engine/src/cookies.js
engine/src/youtube.js
engine/src/player.js
engine/src/server.js
engine/src/index.js
engine/test/formats.test.js
engine/test/cache.test.js
engine/test/protocol.test.js
engine/test/mpv.test.js
ui/  (GTK clone of cliamp-gui chrome, new IPC)
packaging/music-player.desktop
packaging/hypr-window-rules.conf
bin/music-player
```

### Tasks

1. Engine unit cores: formats, URL cache, protocol, EQ
2. mpv JSON IPC wrapper + test against a local ffmpeg file
3. Cookie read + Innertube + poToken + live getInfo
4. Engine server + queue + shutdown
5. GTK UI talking to engine
6. Desktop/Hyprland + close-path verification
7. Live play/seek timing against success criteria

---
