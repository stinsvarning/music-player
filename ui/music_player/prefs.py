from __future__ import annotations

import os
from pathlib import Path

from .spectrum import VIS_MODES


def config_path() -> Path:
    override = os.environ.get("MUSIC_PLAYER_CONFIG")
    if override:
        return Path(override)
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "music-player" / "config.toml"


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
            mode = val.strip().strip("\"'")
            if mode in VIS_MODES:
                return mode
    return VIS_MODES[0]


def save_vis_mode(mode: str, path: Path | None = None) -> None:
    if mode not in VIS_MODES:
        mode = VIS_MODES[0]
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
