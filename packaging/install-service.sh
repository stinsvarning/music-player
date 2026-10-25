#!/usr/bin/env bash
# Install (or remove) the Music engine as a systemd user service.
# Usage: ./packaging/install-service.sh [--prefix DIR | --repo] [--enable] [--now] [--remove]
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PREFIX="${PREFIX:-$HOME/.local}"
UNIT=music-player-engine.service
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
ENGINE=""
ENABLE=0
NOW=0
REMOVE=0

usage() {
  cat <<USAGE
Install the Music engine as a systemd user service ($UNIT).

  ./packaging/install-service.sh [--prefix DIR | --repo] [--enable] [--now]
  ./packaging/install-service.sh --remove

  --prefix DIR  use the engine installed by install.sh under DIR (default: \$HOME/.local)
  --repo        use the engine in this checkout instead
  --engine FILE use this engine entry point (…/engine/src/index.js)
  --enable      start it with the graphical session from now on
  --now         also start it now (an engine that is already running is kept;
                the service then simply exits until the next login)
  --remove      stop, disable and delete the unit

Without the unit the window keeps spawning the engine itself.
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) PREFIX=${2:?--prefix needs a directory}; shift 2 ;;
    --repo) ENGINE="$ROOT/engine/src/index.js"; shift ;;
    --engine) ENGINE=${2:?--engine needs a file}; shift 2 ;;
    --enable) ENABLE=1; shift ;;
    --now) NOW=1; shift ;;
    --remove) REMOVE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [ "$REMOVE" = 1 ]; then
  systemctl --user disable --now "$UNIT" >/dev/null 2>&1 || true
  rm -f "$UNIT_DIR/$UNIT"
  systemctl --user daemon-reload || true
  echo "Removed $UNIT"
  exit 0
fi

if [ -z "$ENGINE" ]; then
  ENGINE="$PREFIX/lib/music-player/engine/src/index.js"
fi
if [ ! -f "$ENGINE" ]; then
  echo "engine not found: $ENGINE (run install.sh first, or pass --repo)" >&2
  exit 1
fi
NODE=$(command -v node || true)
if [ -z "$NODE" ]; then
  echo "node not found on PATH" >&2
  exit 1
fi
# Resolve version-manager shims (mise, asdf, nvm) to the real binary so the
# service does not depend on a shell's PATH.
if command -v mise >/dev/null 2>&1 && mise which node >/dev/null 2>&1; then
  NODE=$(mise which node)
fi
NODE=$(readlink -f "$NODE")

mkdir -p "$UNIT_DIR"
sed -e "s#@NODE@#$NODE#g" -e "s#@ENGINE@#$ENGINE#g" "$ROOT/packaging/systemd/$UNIT.in" > "$UNIT_DIR/$UNIT"
systemctl --user daemon-reload
echo "Installed $UNIT_DIR/$UNIT"
echo "  node:   $NODE"
echo "  engine: $ENGINE"
if [ "$ENABLE" = 1 ]; then
  systemctl --user enable "$UNIT"
fi
if [ "$NOW" = 1 ]; then
  systemctl --user start "$UNIT"
fi
