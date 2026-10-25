# Music

A standalone YouTube Music player for Arch, CachyOS and Omarchy. GTK4 front end, a small Node engine that talks to YouTube Music's Innertube API through [youtubei.js](https://github.com/LuanRT/YouTube.js), and mpv for playback.

Version 0.2.0. Unofficial, and not affiliated with Google or YouTube. It uses the YouTube Music session of a browser already signed in on this computer.

![The deck with the bricks visualizer](docs/screenshots/deck-bricks.png)

![Queue](docs/screenshots/queue.png)

<details>
<summary>More screenshots: wave, waterfall, half-screen</summary>

![Wave](docs/screenshots/deck-wave.png)

![Waterfall](docs/screenshots/deck-waterfall.png)

![Half-screen tile](docs/screenshots/half-screen.png)

</details>

## Features

- **Your library.** Search songs, browse your playlists, and like the current track (it shows up in Liked Music). Premium audio quality is used when the browser session has Premium.
- **Queue.** Drag a row to reorder it (a thin line shows where it will land), or move the selected row with **Alt+↑/↓**. Right-click a queue row to play it next, move it to the top or bottom, start a mix, go to its artist or album, save it or the whole queue to a playlist, copy its link, remove it, or clear everything after the current track. Moving the playing row, or a song that is in the queue twice, never interrupts playback or the gapless hand-over.
- **Undo.** Remove, Start mix and Clear upcoming can be undone with **Ctrl+Z** or the quiet *Removed · Undo* note in the footer (the last ten steps). If the song that was playing is still playing, it keeps playing; if the edit replaced it (a mix, or removing the playing row), it comes back where it was.
- **Library menus.** Right-click a search result or playlist track to play it next, add it to the queue, start a mix, go to its artist or album (as a Library search), save it to a playlist or copy its `music.youtube.com` link. Right-click a playlist to start a mix, rename it or delete it.
- **Playback.** Gapless: the next stream is already queued in mpv when a track ends. Shuffle, repeat (all or one), play similar when the queue runs out, and a sleep timer.
- **Visualizer.** Three looks: bricks, wave and waterfall, plus off. Click the visualizer to cycle bricks → wave → waterfall → off. The player remembers your choice across restarts. It fills the LCD strip and the area around the deck, is capped at 60 fps, and its intensity follows the player volume. Off leaves a still, dark grid and also stops the audio analysis behind it, so it costs next to nothing.
- **Omarchy theme.** Colours come from the current Omarchy theme and repaint live when you switch themes. Accent and peak colours can be overridden in the config.
- **Fits any tile.** The deck keeps its full size on a large screen and shrinks to fit a half-screen or short tile.
- **Desktop integration.** MPRIS, so media keys and other players' controls work. An optional Omarchy bar widget shows the current track and opens the window.
- **Light on resources.** The engine pushes status changes to the window instead of being polled, so an idle player costs almost no CPU.
- **Scriptable.** A local socket, an optional loopback HTTP endpoint and an MCP server expose the same commands. See [docs/agents.md](docs/agents.md).

The window is a client: closing it leaves the engine and the music running. **Ctrl+Q** quits the engine and mpv.

## Requirements

- Node.js 22 or newer, and npm
- mpv
- GTK4 and PyGObject (`gtk4`, `python-gobject`), run with the system `/usr/bin/python3`
- `sqlite` for Firefox, Zen and LibreWolf cookies; `yt-dlp` for Chrome, Chromium, Brave, Edge, Vivaldi and Helium
- A browser on this computer signed in to [YouTube Music](https://music.youtube.com)

## Install

### Arch package

Build the PKGBUILD from a checkout:

```bash
git clone https://github.com/stinsvarning/music-player.git
cd music-player/packaging/aur
makepkg -si
```

The package installs to `/usr`. The Omarchy bar widget and Hyprland snippet are placed in `/usr/share/music-player/` for you to copy if you want them.

### User-local install

```bash
git clone https://github.com/stinsvarning/music-player.git
cd music-player
sudo pacman -S --needed python-gobject gtk4 mpv nodejs npm sqlite yt-dlp
./packaging/install.sh --prefix ~/.local
```

This installs `music-player` to `~/.local/bin` and a desktop entry called **Music**. Make sure `~/.local/bin` is on your `PATH`.

On Omarchy the script also installs two extras, unless you pass `--no-extras`:

- the **Music** bar widget, to `~/.config/omarchy/plugins/llurd.music/` (enable it in the bar if it does not appear)
- a Hyprland window rule, to `~/.config/hypr/music-player.lua` (require it from your `hyprland.lua`)

To open or focus the player with **Super+Shift+M** (Omarchy's default music key), copy the two lines from `packaging/hypr-bindings.lua` into `~/.config/hypr/bindings.lua`.

### Run from a checkout

```bash
cd engine && npm ci && cd ..
./music-player
```

## First run

If no signed-in session is found, the window lists the browsers that have a profile on this computer. Click **Sign in with …** for the one you use; YouTube Music opens in that browser and the player picks up the session. **Check again** re-scans.

**Account → Sign out** forgets the saved session until you sign in again. Your queue is kept.

## Keys

Press **?** in the window for this list.

| Key | Action |
|---|---|
| `Space` | Play / pause |
| `n` / `p` | Next / previous |
| `s` | Stop |
| `←` / `→` | Seek 5 seconds |
| `↑` / `↓` | Volume ±5 (in a focused list: move the selection) |
| `l` | Like or unlike |
| `q` / `m` | Queue / Library view |
| `/` or `Ctrl+F` | Search |
| `Delete` | Remove the selected queue row |
| `Alt+↑` / `Alt+↓` | Move the selected queue row up / down |
| `Ctrl+Z` | Undo the last remove, mix or clear upcoming |
| `Menu` or `Shift+F10` | Context menu |
| `F11` | Fullscreen |
| `Esc` | Leave the search field |
| `Ctrl+Q` | Quit the player and the engine |

## Configuration

Everything is optional. The file is `~/.config/music-player/config.toml`:

```toml
# Which browser session to use. "auto" picks the first signed-in browser it finds.
cookies_from = "auto"
# cookies_from = "firefox:~/.config/zen"

# Visualizer look: bricks, wave, waterfall or off. The look you last clicked is
# remembered by the player and wins over this line at startup. Editing the line
# applies it without a restart, and it becomes the remembered look.
vis_mode = "bricks"

# Override the theme's accent and peak colours.
# accent = "#7aa2f7"
# peak = "#f7768e"
```

## Engine as a systemd user service

By default the window starts the engine when it opens. Run the engine as a user service instead, and it comes up with your graphical session, so media keys and the bar widget work before the window is ever opened:

```bash
./packaging/install-service.sh --enable --now          # the engine installed by install.sh
./packaging/install-service.sh --repo --enable --now   # the engine in this checkout
```

- With the unit installed, opening Music starts the service if needed and attaches to it. If that fails, the window falls back to starting the engine itself.
- **Ctrl+Q** still stops the engine. The service only restarts after a crash, so it stays stopped until your next login or the next time you open Music.
- The unit records the absolute path of `node` (version-manager shims such as mise are resolved). **Rerun the script after upgrading Node.**
- `MUSIC_PLAYER_NO_SYSTEMD=1 music-player` skips the service for one launch.
- Logs: `journalctl --user -u music-player-engine`. Remove it with `./packaging/install-service.sh --remove`.

## Performance

It's light on memory and close to free when idle. While playing, it uses about as much CPU as the browser options, even though it animates a 60 fps visualizer and they mostly show a still page.

| | Playing, window visible | Playing, window hidden | Idle | Memory (PSS / RSS) | Processes |
|---|---|---|---|---|---|
| **music-player** (wave / bricks / waterfall) | 7.2% / 6.1% / 4.5% | 2.9% | 0.4% | ~210 MB / ~335 MB | 3 |
| music-player, visualizer off | 1.0% | 0.8% | 0.4% | same as above | 3 |
| music.youtube.com in Chromium | 3.6% | 2.3% | 8.8% | ~640 MB / ~1.3 GB | 13 |
| Pear Desktop 3.12 (Electron) | 5.5% | 1.8% | 8.6% | ~570 MB / ~1.1 GB | 8 |
| mpv alone (no window, no visualizer) | 0.5% | 0.5% | — | ~59 MB / ~90 MB | 1 |

CPU is a percentage of **one** core, averaged over 60 s and summed over every process involved. Memory is summed too; PSS counts shared pages once.

- **When the window is hidden** (another workspace), nothing is drawn. What's left is mpv decoding plus the visualizer's band analysis.
- **With the visualizer off**, the band analysis stops too, so playback costs about what mpv alone does.
- **Idle** means the window open with nothing playing. The web player keeps animating its home page, so it doesn't idle down.
- **Window size** barely matters: a half-screen and a near-maximized window cost the same.

<details>
<summary>How this was measured</summary>

Measured on 2026-10-25 on an Intel Core Ultra 9 285K (24 cores, integrated graphics) running Arch/Omarchy, Hyprland 0.56, GTK 4.24 and mpv 0.41. Every player played the same 5:45 track. Each figure is the median of two fresh launches. "Visible" means the window was drawn by a headless 60 Hz gamescope compositor at 3840×1600. "Hidden" means it was on a workspace not being shown. Audio output was disabled for every candidate (`--ao=null` for mpv, `--mute-audio --disable-audio-output` for Chromium and Pear), so the audio server's own cost isn't counted. GPU use wasn't measured. music-player ran signed in; Chromium and Pear ran signed out, with ads. The Chromium and Pear numbers come from the same session, before the visualizer optimisations in `de1b5a3`. The visualizer-off row was measured later the same day in a separate session, side by side with wave (wave measured 7.9% visible and 3.1% hidden there).

</details>

## How it works

```
GTK4 window (ui/music_player) ──┐
Omarchy bar widget ─────────────┼── Unix socket ──> engine (engine/src, Node) ──> mpv
music-player-ctl / HTTP / MCP ──┘                     │
                                                      ├── YouTube Music (Innertube, youtubei.js)
                                                      └── MPRIS on D-Bus
```

- **Engine** (`engine/src`). Owns the session, queue and playback. It resolves streams through Innertube, drives one long-lived mpv over JSON IPC, keeps the next track queued for gapless playback, and saves the queue and volume between runs. Only one engine runs at a time, listening on `~/.config/music-player/engine.sock`.
- **Visualizer data.** An mpv audio filter splits the signal into ten bands and reports their levels. The window reads them every 80 ms while playing and draws at most 60 frames per second.
- **Window** (`ui/music_player`). A GTK4 client that subscribes to the engine's status stream and only falls back to slow polling when it has to. It watches the Omarchy theme files and `config.toml` and repaints on change.
- **Packaging** (`packaging/`). `install.sh`, `uninstall.sh`, `install-service.sh` with the systemd unit template, the Arch PKGBUILD, the Omarchy bar widget and the Hyprland snippets.

## Development

```bash
(cd engine && npm ci)    # once
cd engine && node --test
cd ui && /usr/bin/python3 -m unittest discover -s tests
```

Run the last two from the repository root.

The UI tests need the system PyGObject, hence `/usr/bin/python3`. Tests that start mpv run it with `--ao=null`, so they never make a sound.

For a silent, headless engine (on its own socket, for example), set `MUSIC_PLAYER_MPV_ARGS="--ao=null"` and `MUSIC_PLAYER_NO_MPRIS=1`.

## Uninstall

Quit the player first with **Ctrl+Q**.

```bash
./packaging/uninstall.sh --prefix ~/.local
```

This removes the launcher, the installed files, the desktop entry and the engine user service. Your session and config stay. Add `--purge-extras` to also remove the bar widget and Hyprland snippet, and `--purge-config` to delete `~/.config/music-player`.

## License

MIT. See [LICENSE](LICENSE).
