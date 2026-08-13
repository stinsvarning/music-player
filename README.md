# music-player

Standalone YouTube Music player: GTK chrome + Innertube + mpv.

Not cliamp. Not Electron. Seek is real.

```bash
/usr/bin/python3 ~/Projects/music-player/music-player
```

Also installed as `music-player` and a desktop entry named **Music**.

Requires: Node 22+, mpv, Zen logged into YouTube Music (`cookies_from` in `~/.config/music-player/config.toml`).

Engine tests:

```bash
cd engine && node --test
```

Design: `docs/superpowers/specs/2026-08-14-innertube-mpv-player-design.md`
