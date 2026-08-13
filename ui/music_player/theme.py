from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str
    panel: str
    fg: str
    muted: str
    accent: str
    peak: str
    highlight: str


PALETTES: list[Palette] = [
    Palette(
        name="mint",
        bg="#0b0e0b",
        panel="#101410",
        fg="#b6e0b4",
        muted="#5e7a5c",
        accent="#7dcf7a",
        peak="#e0a24a",
        highlight="#1a2418",
    ),
    Palette(
        name="amber",
        bg="#120e08",
        panel="#1a140c",
        fg="#f0d7a0",
        muted="#8a7048",
        accent="#e0a24a",
        peak="#7dcf7a",
        highlight="#2a1e10",
    ),
    Palette(
        name="ice",
        bg="#0a1014",
        panel="#10181e",
        fg="#c5e4f0",
        muted="#5a7a88",
        accent="#6ec8e0",
        peak="#e0a24a",
        highlight="#162228",
    ),
    Palette(
        name="violet",
        bg="#100814",
        panel="#180e1e",
        fg="#e0c8f0",
        muted="#7a5a88",
        accent="#c48ae0",
        peak="#e0a24a",
        highlight="#24162c",
    ),
]


def palette_named(name: str) -> Palette:
    for palette in PALETTES:
        if palette.name == name:
            return palette
    return PALETTES[0]


def _toml_colors(text: str) -> dict[str, str]:
    colors: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        val = val.strip()
        quoted = re.match(r"""(['"])(.*?)\1""", val)
        if quoted:
            val = quoted.group(2)
        else:
            val = val.split("#", 1)[0].strip()
        if re.fullmatch(r"#[0-9A-Fa-f]{3,8}", val):
            colors[key.strip()] = val
    return colors


def load_omarchy_palette(path: str | Path) -> Palette:
    text = Path(path).read_text()
    c = _toml_colors(text)
    return Palette(
        name="omarchy",
        bg=c.get("background") or c.get("bg") or "#0b0e0b",
        panel=c.get("lighter_bg") or c.get("bg") or "#101410",
        fg=c.get("foreground") or c.get("fg") or "#b6e0b4",
        muted=c.get("muted") or c.get("dark_fg") or "#5e7a5c",
        accent=c.get("accent") or c.get("green") or "#7dcf7a",
        peak=c.get("orange") or c.get("yellow") or "#e0a24a",
        highlight=c.get("selection_background") or c.get("lighter_bg") or "#1a2418",
    )


def css_for(palette: Palette) -> str:
    return f"""
        :root {{
            --bg: {palette.bg};
            --panel: {palette.panel};
            --fg: {palette.fg};
            --muted: {palette.muted};
            --accent: {palette.accent};
            --peak: {palette.peak};
            --highlight: {palette.highlight};
        }}
        window, .app-window {{
            background: {palette.bg};
            color: {palette.fg};
            font-family: "JetBrainsMono Nerd Font", "JetBrains Mono", monospace;
            font-size: 12px;
        }}
        .chrome {{
            background: {palette.panel};
            padding: 10px 14px 8px 14px;
        }}
        .brand {{
            color: {palette.muted};
            letter-spacing: 3px;
            font-weight: 700;
            font-size: 13px;
        }}
        .subtitle {{
            color: {palette.muted};
        }}
        .title {{
            color: {palette.accent};
            font-size: 16px;
            font-weight: 700;
        }}
        .meta {{
            color: {palette.muted};
        }}
        button {{
            font-family: "JetBrainsMono Nerd Font", "JetBrains Mono", monospace;
            background: {palette.bg};
            color: {palette.fg};
            border: 1px solid {palette.muted};
            border-radius: 3px;
            padding: 4px 10px;
            min-height: 28px;
        }}
        button:hover {{
            border-color: {palette.accent};
            color: {palette.accent};
        }}
        button.active, button:checked, togglebutton:checked {{
            background: {palette.highlight};
            color: {palette.accent};
            border-color: {palette.accent};
        }}
        .swatch {{
            min-width: 16px;
            min-height: 16px;
            padding: 0;
            border-radius: 2px;
            border: 1px solid {palette.muted};
        }}
        .swatch.active {{
            border-color: {palette.fg};
        }}
        notebook, notebook > header, notebook > header > tabs {{
            background: {palette.bg};
        }}
        notebook > header tab {{
            background: {palette.bg};
            color: {palette.muted};
            padding: 6px 14px;
            border: none;
            box-shadow: none;
        }}
        notebook > header tab:checked {{
            color: {palette.accent};
            box-shadow: inset 0 -2px 0 {palette.accent};
        }}
        list, listview, .list {{
            background: {palette.bg};
            color: {palette.fg};
        }}
        row:selected, .current-track {{
            background: {palette.highlight};
            color: {palette.accent};
        }}
        entry {{
            background: {palette.bg};
            color: {palette.fg};
            border: 1px solid {palette.muted};
            border-radius: 2px;
            padding: 4px 8px;
        }}
        entry:focus {{
            border-color: {palette.accent};
        }}
        scale trough {{
            background: #1c221c;
            min-height: 6px;
            border-radius: 2px;
        }}
        scale highlight {{
            background: {palette.accent};
        }}
        .footer {{
            color: {palette.muted};
            padding: 6px 12px;
            border-top: 1px solid #1c221c;
        }}
        .footer .codec {{
            color: {palette.peak};
        }}
        .hint {{
            color: {palette.muted};
        }}
        scrollbar slider {{
            background: {palette.muted};
            min-width: 6px;
        }}
        """
