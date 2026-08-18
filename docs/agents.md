# Agent control

The engine is the app. GTK and the bar are clients. Talk to the Unix socket; do not scrape the window.

Socket: `~/.config/music-player/engine.sock` (mode `600`, this user only). Override with `MUSIC_PLAYER_SOCK`.

```bash
node engine/bin/music-player-ctl help
node engine/bin/music-player-ctl status
node engine/bin/music-player-ctl search "suede"
node engine/bin/music-player-ctl play --id VIDEO_ID
```

`help` / `commands` lists every verb with `risk`: `read`, `write`, or `dangerous`. Prefer `read` and `write`. Do not call `shutdown` or `auth.refresh` unless the user asked. Cookies and stream URLs never appear in `help`.

Optional `id` on a request is echoed on the reply. Ctrl+Q still quits the engine.

## Loopback HTTP

A phone or remote agent that already has a tunnel onto this machine can use the same JSON on loopback HTTP. The engine binds **`127.0.0.1:18741` only** — never the LAN. Pairing token: `~/.config/music-player/http.token` (mode `600`, created on first start). `shutdown` and `auth.refresh` are refused on HTTP unless `MUSIC_PLAYER_HTTP_DANGEROUS=1`.

```bash
TOKEN=$(cat ~/.config/music-player/http.token)
curl -sS http://127.0.0.1:18741/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "content-type: application/json" \
  -d '{"cmd":"status"}'

node engine/bin/music-player-ctl --http status

# ssh -N -L 18741:127.0.0.1:18741 user@this-machine
```

Set `MUSIC_PLAYER_HTTP=off` to leave the port closed. Override the port with `MUSIC_PLAYER_HTTP_PORT`.

## MCP

Any MCP client can attach over stdio. The process talks to the Unix socket, so the engine must already be running. Tools are the catalog minus `help` / `commands`. `shutdown` and `auth.refresh` stay hidden unless `MUSIC_PLAYER_MCP_DANGEROUS=1`.

```text
command: node
args: [engine/bin/music-player-mcp]
```

From an install, point `args` at `~/.local/lib/music-player/engine/bin/music-player-mcp`. Tool names use underscores (`queue_save`, `track_play`). How you register that command depends on the client.

## Tests

```bash
cd engine && node --test
cd ui && /usr/bin/python3 -m unittest discover -s tests
```

GTK layout tests need system PyGObject (`/usr/bin/python3`).
