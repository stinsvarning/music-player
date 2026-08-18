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


FALLBACK = Palette(
    name="fallback",
    bg="#121212",
    panel="#1a1a1a",
    fg="#e6e6e6",
    muted="#8a8a8a",
    accent="#7aa2f7",
    peak="#e0af68",
    highlight="#1e2430",
)

# Kept for older tests / optional naming. Not shown in the window.
PALETTES: list[Palette] = [FALLBACK]


def omarchy_state_dir() -> Path:
    return Path.home() / ".local/state/omarchy/current"


def omarchy_current_dir() -> Path:
    return omarchy_state_dir()


def omarchy_colors_path() -> Path:
    return omarchy_state_dir() / "theme" / "colors.toml"


def omarchy_colors_paths() -> list[Path]:
    paths = [
        omarchy_state_dir() / "theme" / "colors.toml",
        Path.home() / ".config/omarchy/current/theme/colors.toml",
    ]
    try:
        slug = (omarchy_state_dir() / "theme.name").read_text().strip()
    except OSError:
        slug = ""
    if slug:
        paths.append(Path.home() / ".config/omarchy/themes" / slug / "colors.toml")
    seen: set[str] = set()
    out: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def palette_named(name: str) -> Palette:
    if name == "omarchy":
        return load_active_palette()
    return FALLBACK


def load_active_palette() -> Palette:
    for path in omarchy_colors_paths():
        if path.is_file():
            try:
                return load_omarchy_palette(path)
            except OSError:
                continue
    return FALLBACK


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


def _hex_rgb(value: str) -> tuple[int, int, int]:
    raw = value.lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def mix_hex(left: str, right: str, amount: float) -> str:
    t = max(0.0, min(1.0, amount))
    lr, lg, lb = _hex_rgb(left)
    rr, rg, rb = _hex_rgb(right)
    return "#{:02x}{:02x}{:02x}".format(
        int(lr + (rr - lr) * t),
        int(lg + (rg - lg) * t),
        int(lb + (rb - lb) * t),
    )


def luminance(value: str) -> float:
    r, g, b = _hex_rgb(value)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def _rgb_to_hsv(r: int, g: int, b: int) -> tuple[float, float, float]:
    rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
    mx, mn = max(rf, gf, bf), min(rf, gf, bf)
    delta = mx - mn
    if delta == 0:
        hue = 0.0
    elif mx == rf:
        hue = (60 * ((gf - bf) / delta) + 360) % 360
    elif mx == gf:
        hue = (60 * ((bf - rf) / delta) + 120) % 360
    else:
        hue = (60 * ((rf - gf) / delta) + 240) % 360
    sat = 0.0 if mx == 0 else delta / mx
    return hue, sat, mx


def _hsv_to_hex(h: float, s: float, v: float) -> str:
    c = v * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = v - c
    if h < 60:
        rp, gp, bp = c, x, 0.0
    elif h < 120:
        rp, gp, bp = x, c, 0.0
    elif h < 180:
        rp, gp, bp = 0.0, c, x
    elif h < 240:
        rp, gp, bp = 0.0, x, c
    elif h < 300:
        rp, gp, bp = x, 0.0, c
    else:
        rp, gp, bp = c, 0.0, x
    return "#{:02x}{:02x}{:02x}".format(
        int(round((rp + m) * 255)),
        int(round((gp + m) * 255)),
        int(round((bp + m) * 255)),
    )


def saturation(value: str) -> float:
    return _rgb_to_hsv(*_hex_rgb(value))[1]


def boost_accent(value: str) -> str:
    h, s, v = _rgb_to_hsv(*_hex_rgb(value))
    if s < 0.38:
        s = 0.58
    if v < 0.62:
        v = 0.74
    return _hsv_to_hex(h, min(0.78, s), min(0.86, v))


def with_accent(palette: Palette, accent: str) -> Palette:
    color = boost_accent(accent)
    return Palette(
        name=palette.name,
        bg=palette.bg,
        panel=palette.panel,
        fg=palette.fg,
        muted=palette.muted,
        accent=color,
        peak=palette.peak,
        highlight=mix_hex(palette.bg, color, 0.34),
    )


def accent_from_pixbuf(pix) -> str | None:
    if pix is None:
        return None
    width = pix.get_width()
    height = pix.get_height()
    channels = pix.get_n_channels()
    stride = pix.get_rowstride()
    data = pix.get_pixels()
    best_hex = None
    best_score = 0.0
    step = max(1, min(width, height) // 12)
    for y in range(0, height, step):
        for x in range(0, width, step):
            i = y * stride + x * channels
            r, g, b = data[i], data[i + 1], data[i + 2]
            if max(r, g, b) < 28 or min(r, g, b) > 232:
                continue
            _h, sat, val = _rgb_to_hsv(r, g, b)
            score = sat * sat * val
            if score > best_score:
                best_score = score
                best_hex = "#{:02x}{:02x}{:02x}".format(r, g, b)
    if best_hex is None or best_score < 0.04:
        return None
    return best_hex


def palette_from_colors(colors: dict[str, str]) -> Palette:
    bg = colors.get("background") or colors.get("bg") or FALLBACK.bg
    fg = colors.get("foreground") or colors.get("fg") or FALLBACK.fg
    muted = colors.get("muted") or colors.get("dark_fg") or FALLBACK.muted
    accent = boost_accent(colors.get("accent") or colors.get("blue") or colors.get("green") or FALLBACK.accent)
    peak = colors.get("orange") or colors.get("yellow") or FALLBACK.peak
    panel = colors.get("lighter_bg") or mix_hex(bg, fg, 0.08)
    selection = colors.get("selection_background") or colors.get("selection")
    if selection and luminance(selection) < 0.45:
        highlight = selection
    else:
        highlight = mix_hex(bg, accent, 0.34)
    return Palette(
        name="omarchy" if colors else FALLBACK.name,
        bg=bg,
        panel=panel,
        fg=fg,
        muted=muted,
        accent=accent,
        peak=peak,
        highlight=highlight,
    )


def load_omarchy_palette_text(text: str) -> Palette:
    return palette_from_colors(_toml_colors(text))


def load_omarchy_palette(path: str | Path) -> Palette:
    return load_omarchy_palette_text(Path(path).read_text())


def css_for(palette: Palette) -> str:
    select = mix_hex(palette.bg, palette.muted, 0.45)
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
        window, .app-window, headerbar {{
            background: {palette.bg};
            color: {palette.fg};
            font-size: 12px;
        }}
        headerbar {{
            background: {palette.panel};
            padding: 2px 8px;
            min-height: 28px;
        }}
        .chrome {{
            background: {palette.panel};
            padding: 8px 12px;
        }}
        .login-veil {{
            background: {mix_hex(palette.bg, "#000000", 0.35)};
        }}
        .login-card {{
            background: {palette.panel};
            color: {palette.fg};
            border: 1px solid {palette.muted};
            border-radius: 10px;
            padding: 20px 22px;
            min-width: 320px;
        }}
        .now-playing {{
            background-image: linear-gradient(
                90deg,
                {mix_hex(palette.panel, palette.accent, 0.42)} 0%,
                {palette.panel} 72%
            );
        }}
        .subtitle {{
            color: {palette.muted};
            font-size: 11px;
        }}
        .title {{
            color: {palette.accent};
            font-size: 15px;
            font-weight: 600;
        }}
        .header-title {{
            color: {palette.fg};
            font-weight: 600;
            font-size: 13px;
        }}
        .meta, .hint {{
            color: {palette.muted};
        }}
        .lyric-line {{
            color: {palette.fg};
            background: transparent;
            font-size: 13px;
            padding: 2px 8px;
        }}
        list.lyrics, list.lyrics row, list.lyrics row:hover, list.lyrics row:selected {{
            background: transparent;
            box-shadow: none;
        }}
        scrolledwindow, viewport {{
            background: {palette.bg};
        }}
        button {{
            background: {palette.bg};
            color: {palette.fg};
            border: 1px solid {palette.muted};
            border-radius: 6px;
            padding: 2px 8px;
            min-height: 28px;
            min-width: 28px;
        }}
        button.flat {{
            background: transparent;
            border-color: transparent;
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
        notebook, notebook > header, notebook > header > tabs, notebook > stack, .tab-page, .tab-caption {{
            background: {palette.bg};
            color: {palette.fg};
            border: none;
            box-shadow: none;
        }}
        notebook > header tab {{
            background: {palette.bg};
            color: {palette.muted};
            padding: 6px 12px;
            border: none;
            box-shadow: none;
        }}
        notebook > header tab:checked {{
            color: {palette.accent};
            box-shadow: inset 0 -2px 0 {palette.accent};
        }}
        .tab-caption {{
            min-height: 24px;
            padding: 2px 0 0;
        }}
        entry.tab-search {{
            min-height: 22px;
            min-width: 240px;
            margin: 4px 8px 4px 0;
            padding: 1px 8px;
        }}
        button.eq-preset {{
            background: transparent;
            color: {palette.muted};
            border-color: {mix_hex(palette.bg, palette.muted, 0.55)};
            min-height: 20px;
            padding: 0 8px;
        }}
        button.eq-preset:hover {{
            color: {palette.fg};
            border-color: {palette.accent};
        }}
        button.eq-preset:checked {{
            background: {palette.highlight};
            color: {palette.accent};
            border-color: {palette.accent};
        }}
        scale {{
            background: transparent;
        }}
        scale slider {{
            background: {palette.muted};
            min-width: 12px;
            min-height: 12px;
        }}
        list, listview, .list {{
            background: {palette.bg};
            color: {palette.fg};
            padding-bottom: 24px;
        }}
        headerbar {{
            padding-left: 4px;
        }}
        .header-titles {{
            margin-left: 8px;
        }}
        row:selected {{
            background: {select};
            color: {palette.fg};
        }}
        row.unplayable, row.unplayable label {{
            color: {palette.muted};
            opacity: 0.5;
        }}
        .current-track {{
            background: {palette.highlight};
            color: {palette.accent};
            box-shadow: inset 5px 0 0 {palette.accent};
        }}
        .current-track:selected {{
            background: {mix_hex(palette.highlight, palette.accent, 0.2)};
            color: {palette.accent};
            box-shadow: inset 5px 0 0 {palette.peak};
        }}
        entry {{
            background: {palette.bg};
            color: {palette.fg};
            border: 1px solid {palette.muted};
            border-radius: 4px;
            padding: 4px 8px;
        }}
        entry:focus {{
            border-color: {palette.accent};
        }}
        scale trough {{
            background: {mix_hex(palette.bg, palette.muted, 0.35)};
            min-height: 6px;
            border-radius: 2px;
        }}
        scale highlight {{
            background: {palette.accent};
        }}
        .ctx-menu {{
            background: {palette.panel};
            padding: 4px;
        }}
        .ctx-menu button {{
            min-height: 24px;
            padding: 3px 10px;
            border: none;
            border-radius: 2px;
        }}
        .ctx-menu button:hover {{
            background: {palette.highlight};
        }}
        popover {{
            background: {palette.panel};
            color: {palette.fg};
        }}
        scrollbar slider {{
            background: {palette.muted};
            min-width: 6px;
        }}
        """
