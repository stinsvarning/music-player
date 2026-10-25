from __future__ import annotations

import json
import os
from pathlib import Path

from .spectrum import VIS_MODES, normalize_vis, vis_name


def config_path() -> Path:
    override = os.environ.get("MUSIC_PLAYER_CONFIG")
    if override:
        return Path(override)
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "music-player" / "config.toml"


def _uncomment(raw: str) -> str:
    """Drop a trailing comment, keeping `#` inside quotes (hex colors)."""
    quote = ""
    for index, ch in enumerate(raw):
        if ch in {'"', "'"}:
            if quote == ch:
                quote = ""
            elif not quote:
                quote = ch
            continue
        if ch == "#" and not quote:
            return raw[:index]
    return raw


def _config_assignments(path: Path | None = None) -> list[tuple[str, str]]:
    file = path or config_path()
    try:
        text = file.read_text()
    except OSError:
        return []
    rows: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = _uncomment(raw).strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        rows.append((key.strip().lower(), val.strip().strip("\"'")))
    return rows


def load_color_overrides(path: Path | None = None) -> dict[str, str]:
    """Optional accent and peak from this app's config.toml, not the desktop theme."""
    out: dict[str, str] = {}
    for key, val in _config_assignments(path):
        if key in {"accent", "peak"} and val.startswith("#") and len(val) in {4, 7, 9}:
            out[key] = val
    return out


def config_vis_mode(path: Path | None = None) -> str | None:
    """vis_mode as written in config.toml (bricks/wave/waterfall/off), or None if unset."""
    file = path or config_path()
    try:
        text = file.read_text()
    except OSError:
        return None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line.lower().startswith("vis_mode"):
            _, _, val = line.partition("=")
            return normalize_vis(val.strip().strip("\"'"))
    return None


def load_vis_mode(path: Path | None = None) -> str:
    return config_vis_mode(path) or VIS_MODES[0]


def session_path() -> Path:
    """The engine's state file (queue, volume, EQ, last visualizer look)."""
    override = os.environ.get("MUSIC_PLAYER_SESSION")
    if override:
        return Path(override)
    return config_path().parent / "session.json"


def saved_vis_mode(path: Path | None = None) -> str | None:
    """The look last picked in the window, as the engine saved it; None if never."""
    try:
        data = json.loads((path or session_path()).read_text())
    except (OSError, ValueError):
        return None
    return vis_name(data.get("vis_mode")) if isinstance(data, dict) else None


def initial_vis_mode() -> str:
    """Saved choice, else config.toml's vis_mode, else bricks."""
    return saved_vis_mode() or load_vis_mode()
