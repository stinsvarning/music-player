#!/usr/bin/env bash
# Install music-player for the current user (Arch / CachyOS / Omarchy).
# Usage: ./packaging/install.sh [--prefix DIR] [--no-extras]
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PREFIX="${PREFIX:-$HOME/.local}"
EXTRAS=1
VERSION=$(tr -d '[:space:]' < "$ROOT/VERSION")

usage() {
  cat <<EOF
Install Music ${VERSION} (GTK + Node engine + mpv) for this user.

  ./packaging/install.sh [--prefix DIR] [--no-extras]

  --prefix DIR   install root (default: \$HOME/.local)
  --no-extras    skip optional Omarchy bar plugin and Hyprland snippet

Needs: python-gobject, gtk4, mpv, nodejs (>=22), npm, sqlite, yt-dlp

Uninstall with: ./packaging/uninstall.sh [--prefix DIR]
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --prefix)
      PREFIX=${2:?--prefix needs a directory}
      shift 2
      ;;
    --no-extras)
      EXTRAS=0
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
BINDIR="$PREFIX/bin"
APPDIR="$PREFIX/share/applications"

mkdir -p "$DEST" "$BINDIR" "$APPDIR"

install -m 0755 "$ROOT/music-player" "$DEST/music-player"
install -m 0644 "$ROOT/VERSION" "$DEST/VERSION"
install -m 0644 "$ROOT/LICENSE" "$DEST/LICENSE"
printf '%s\n' "$PREFIX" > "$DEST/prefix"
rm -rf "$DEST/ui"
cp -a "$ROOT/ui" "$DEST/ui"
rm -rf "$DEST/engine"
mkdir -p "$DEST/engine"
cp -a "$ROOT/engine/src" "$ROOT/engine/bin" "$ROOT/engine/package.json" "$ROOT/engine/package-lock.json" "$DEST/engine/"

(
  cd "$DEST/engine"
  npm ci --omit=dev
)

cat > "$BINDIR/music-player" <<EOF
#!/bin/sh
exec /usr/bin/python3 "$DEST/music-player" "\$@"
EOF
chmod 0755 "$BINDIR/music-player"

{
  echo "[Desktop Entry]"
  echo "Type=Application"
  echo "Version=$VERSION"
  echo "Name=Music"
  echo "Comment=YouTube Music player (Innertube + mpv)"
  echo "Exec=$BINDIR/music-player"
  echo "Icon=audio-x-generic"
  echo "Terminal=false"
  echo "Categories=AudioVideo;Audio;Player;"
  echo "StartupWMClass=stream.music.Player"
} > "$APPDIR/music-player.desktop"

if [ "$EXTRAS" = 1 ] && [ -d "${XDG_CONFIG_HOME:-$HOME/.config}/omarchy" ]; then
  plug="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/llurd.music"
  mkdir -p "$plug"
  cp -a "$ROOT/packaging/llurd.music/." "$plug/"
  echo "Omarchy bar plugin: $plug"
  echo "Enable the Music widget in the bar if it is not already listed."
fi

if [ "$EXTRAS" = 1 ] && [ -d "${XDG_CONFIG_HOME:-$HOME/.config}/hypr" ]; then
  dest="${XDG_CONFIG_HOME:-$HOME/.config}/hypr/music-player.lua"
  cp "$ROOT/packaging/hypr-window-rules.conf" "$dest"
  echo "Hyprland snippet: $dest"
  echo "Require it from hyprland.lua if the Music window is not already floated."
fi

echo "Installed Music $VERSION -> $BINDIR/music-player"
echo "Desktop entry -> $APPDIR/music-player.desktop"
echo "If the command is not found, add $BINDIR to PATH."
echo "Quit with Ctrl+Q before uninstalling. See packaging/uninstall.sh."
