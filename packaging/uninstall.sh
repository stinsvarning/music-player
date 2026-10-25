#!/usr/bin/env bash
# Remove a user install created by packaging/install.sh.
# Does not delete ~/.config/music-player unless --purge-config.
set -euo pipefail

PREFIX="${PREFIX:-$HOME/.local}"
PURGE_EXTRAS=0
PURGE_CONFIG=0

usage() {
  cat <<EOF
Uninstall Music from a prefix created by install.sh.

  ./packaging/uninstall.sh [--prefix DIR] [--purge-extras] [--purge-config]

  --prefix DIR      install root (default: \$HOME/.local)
  --purge-extras    also remove the Omarchy bar plugin and Hyprland snippet
  --purge-config    also delete ~/.config/music-player (session, cookies)

Quit the player first (Ctrl+Q) so the engine is not running.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --prefix)
      PREFIX=${2:?--prefix needs a directory}
      shift 2
      ;;
    --purge-extras)
      PURGE_EXTRAS=1
      shift
      ;;
    --purge-config)
      PURGE_CONFIG=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

DEST="$PREFIX/lib/music-player"
if [ -f "$DEST/prefix" ]; then
  PREFIX=$(tr -d '[:space:]' < "$DEST/prefix")
  DEST="$PREFIX/lib/music-player"
fi

BINDIR="$PREFIX/bin"
APPDIR="$PREFIX/share/applications"
CTL="$DEST/engine/bin/music-player-ctl"

if [ -x "$CTL" ] && command -v node >/dev/null 2>&1; then
  node "$CTL" shutdown >/dev/null 2>&1 || true
fi

UNIT_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/music-player-engine.service"
if [ -f "$UNIT_FILE" ] && command -v systemctl >/dev/null 2>&1; then
  systemctl --user disable --now music-player-engine.service >/dev/null 2>&1 || true
  rm -f "$UNIT_FILE"
  systemctl --user daemon-reload >/dev/null 2>&1 || true
  echo "Removed the music-player-engine user service"
fi

rm -f "$BINDIR/music-player"
rm -f "$APPDIR/music-player.desktop"
rm -rf "$DEST"

if [ "$PURGE_EXTRAS" = 1 ]; then
  rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/llurd.music"
  rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/hypr/music-player.lua"
fi

if [ "$PURGE_CONFIG" = 1 ]; then
  rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/music-player"
fi

echo "Removed Music from $PREFIX"
if [ "$PURGE_EXTRAS" != 1 ]; then
  echo "Omarchy plugin and Hyprland snippet were left in place. Use --purge-extras to remove them."
fi
if [ "$PURGE_CONFIG" != 1 ]; then
  echo "Config at ~/.config/music-player was left in place. Use --purge-config to delete session and cookies."
fi
