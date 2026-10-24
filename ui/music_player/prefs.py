from __future__ import annotations

import os
from pathlib import Path

from .spectrum import VIS_MODES, normalize_vis


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


def load_vis_mode(path: Path | None = None) -> str:
    file = path or config_path()
    try:
        text = file.read_text()
    except OSError:
        return VIS_MODES[0]
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line.lower().startswith("vis_mode"):
            _, _, val = line.partition("=")
            return normalize_vis(val.strip().strip("\"'"))
    return VIS_MODES[0]


def save_vis_mode(mode: str, path: Path | None = None) -> None:
    mode = normalize_vis(mode)
    file = path or config_path()
    try:
        text = file.read_text()
    except OSError:
        text = ""
    lines = text.splitlines()
    out: list[str] = []
    replaced = False
    for line in lines:
        bare = line.split("#", 1)[0].strip()
        if bare.lower().startswith("vis_mode"):
            out.append(f'vis_mode = "{mode}"')
            replaced = True
        else:
            out.append(line)
    if not replaced:
        if out and out[-1] != "":
            out.append("")
        out.append(f'vis_mode = "{mode}"')
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text("\n".join(out) + "\n")
