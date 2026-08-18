# Music

Standalone YouTube Music player: GTK4 chrome, an Innertube engine, and mpv.

Not cliamp. Not Pear. Not Electron. Seek is a real HTTP range seek in mpv.

**Version 0.1.0.** Unofficial client. It uses a YouTube Music session from a browser on this computer. Not affiliated with Google or YouTube.

Works on **Omarchy** and other Arch-family systems including **CachyOS**. The bar chip and Hyprland float rules are Omarchy extras and are optional.

## Needs

- Node 22+ (`nodejs`, `npm`)
- mpv
- GTK4 / PyGObject (`python-gobject`, `gtk4`)
- A browser on this machine signed into [YouTube Music](https://music.youtube.com)

## Install (Arch / CachyOS)

From a checkout of this repository:

```bash
sudo pacman -S --needed python-gobject gtk4 mpv nodejs npm
./packaging/install.sh --no-extras --prefix ~/.local
```

That puts `music-player` on `PATH` (`~/.local/bin`) and a desktop entry named **Music**. Add `~/.local/bin` to `PATH` if your shell does not already.

After you publish the repo:

```bash
git clone https://github.com/YOURUSER/music-player.git
cd music-player
sudo pacman -S --needed python-gobject gtk4 mpv nodejs npm
./packaging/install.sh --no-extras
```

Run from the clone without installing:

```bash
/usr/bin/python3 ./music-player
```

## Install (Omarchy)

Same as CachyOS, but keep the extras so the bar chip and float rule are copied:

```bash
sudo pacman -S --needed python-gobject gtk4 mpv nodejs npm
./packaging/install.sh --prefix ~/.local
```

If `~/.config/omarchy` exists, install copies the **Music** bar widget to `~/.config/omarchy/plugins/llurd.music/`. Enable the widget in the bar if it is not listed. If `~/.config/hypr` exists, it writes `~/.config/hypr/music-player.lua` (float 920×720). Require that file from your Hyprland config if the window is not already floated.

The same raise-or-launch as the bar chip can be bound to **Super+Shift+M** (Omarchy’s default Music key, normally Spotify). Copy the two lines from `packaging/hypr-bindings.lua` into `~/.config/hypr/bindings.lua`.

Missing Omarchy files does not prevent launch. The window uses a built-in fallback palette.

Premium is used when that browser session has it. Quality is **best available audio-only**: `AUDIO_QUALITY_HIGH` first, then bitrate (itag 774 Opus or 141 AAC 256 beat 140 AAC 128).

## Uninstall

Quit the player first (**Ctrl+Q**).

```bash
./packaging/uninstall.sh --prefix ~/.local
```

That removes the binary, library tree, and desktop entry. It leaves your session and cookies.

```bash
./packaging/uninstall.sh --purge-extras    # also drop the bar plugin and Hyprland snippet
./packaging/uninstall.sh --purge-config    # also delete ~/.config/music-player
```

## First run / login

The engine looks for a YouTube Music session in this order:

1. `cookies_from` in `~/.config/music-player/config.toml` (optional), e.g. `firefox:~/.config/zen`
2. A previously saved header at `~/.config/music-player/cookies.header` (mode `600`)
3. A scan of known browsers: Zen, Firefox, LibreWolf, Chrome, Chromium, Brave, Edge, Vivaldi, Helium (including some Flatpak paths)

If nothing is logged in, the window shows a sign-in card. Click **Sign in** — that opens YouTube Music in your browser. The app watches for the session and hides the card when it finds one. **Check again** forces a browser rescan (it does not reuse a stale saved header).

The person icon in the header shows the current session. **Sign out** forgets `cookies.header` and stays signed out even if the browser is still logged in. Click **Sign in** when you want the app to use that browser account again. The queue on disk stays. Copying `cookies.header` from another machine is the wrong fix.

```toml
# ~/.config/music-player/config.toml — optional
cookies_from = "auto"
# cookies_from = "firefox:~/.config/zen"
```

## Window vs engine

| Action | What happens |
|---|---|
| Close the window / Super+W / Super+X | Hides the window. **Audio keeps playing.** |
| Ctrl+Q | Quits the engine and mpv. |
| Open Music again | Attaches to the running engine if it is still up. |

The engine is a singleton (`engine.lock` + live-socket check). A second start does not spawn another mpv.

## What is saved

`~/.config/music-player/session.json` (mode `600`): queue, current track, playhead, shuffle, repeat, Play similar, volume, EQ, and an active sleep deadline. Restart stays **stopped** until you hit play, then seeks to the saved position. A sleep timer that already expired while the engine was down is dropped, not fired.

Stream URLs go in `url-cache.json` until the signed `expire=` time.

EQ presets are **Flat / Warm / Vocal / Bass / Night**, with a preamp so the peak boost cannot sum above 0 dB. Play similar starts **off**.

## Agent control

The engine is the app. GTK and the bar are clients. A local agent should talk to the Unix socket, not scrape the window.

Socket: `~/.config/music-player/engine.sock` (mode `600`, this user only). Override with `MUSIC_PLAYER_SOCK`.

```bash
node engine/bin/music-player-ctl help
node engine/bin/music-player-ctl status
node engine/bin/music-player-ctl search "suede"
node engine/bin/music-player-ctl play --id VIDEO_ID
```

`help` / `commands` returns every verb with `risk`: `read`, `write`, or `dangerous`. Prefer `read` + `write`. Do not call `shutdown` or `auth.refresh` unless the user asked. Cookies and stream URLs never appear in `help`.

Optional `id` on a request is echoed on the reply. Ctrl+Q still quits the engine.

A phone or remote agent that already has a tunnel onto this machine can use the same JSON on loopback HTTP. The engine binds **`127.0.0.1:18741` only** — never the LAN. Pairing token: `~/.config/music-player/http.token` (mode `600`, created on first start). `shutdown` and `auth.refresh` are refused on HTTP unless `MUSIC_PLAYER_HTTP_DANGEROUS=1`.

```bash
TOKEN=$(cat ~/.config/music-player/http.token)
curl -sS http://127.0.0.1:18741/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "content-type: application/json" \
  -d '{"cmd":"status"}'

node engine/bin/music-player-ctl --http status

# from a phone agent, tunnel first:
# ssh -N -L 18741:127.0.0.1:18741 user@this-machine
```

Set `MUSIC_PLAYER_HTTP=off` to leave the port closed. Override the port with `MUSIC_PLAYER_HTTP_PORT`. The token is never printed by `help`.

Grok Bot can also use the stdio MCP server. It talks to the Unix socket (engine must already be running). Tools are the catalog minus `help` / `commands`; `shutdown` and `auth.refresh` stay hidden unless `MUSIC_PLAYER_MCP_DANGEROUS=1`.

```toml
# ~/.grok/config.toml — use the clone or the install prefix
[mcp_servers.music]
command = "node"
args = ["engine/bin/music-player-mcp"]
```

Run Grok from the clone root, or put the absolute path to `engine/bin/music-player-mcp` under your install prefix (`~/.local/lib/music-player/engine/bin/music-player-mcp`).

Then `/mcps` and refresh. Tool names use underscores (`queue_save`, `track_play`). Prefer `read` + `write`.

## Tests

```bash
cd engine && node --test
cd ui && /usr/bin/python3 -m unittest discover -s tests
```

GTK layout tests need system PyGObject (`/usr/bin/python3`).

## License

MIT. See [LICENSE](LICENSE).
