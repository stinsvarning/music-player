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
    from .prefs import load_color_overrides

    palette = FALLBACK
    for path in omarchy_colors_paths():
        if path.is_file():
            try:
                palette = load_omarchy_palette(path)
                break
            except OSError:
                continue
    return apply_color_overrides(palette, load_color_overrides())


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
    color = accent
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


_STRUCTURAL = {
    "mode",
    "background",
    "bg",
    "foreground",
    "fg",
    "muted",
    "cursor",
    "selection",
    "selection_background",
    "selection_foreground",
    "dark_bg",
    "dark_background",
    "darker_bg",
    "darker_background",
    "lighter_bg",
    "lighter_background",
    "dark_fg",
    "dark_foreground",
    "light_fg",
    "light_foreground",
    "bright_fg",
    "bright_foreground",
}


def _color_key(name: str) -> str:
    return (name or "").strip().lower().replace(" ", "_")


def contrast_ratio(left: str, right: str) -> float:
    light = max(luminance(left), luminance(right))
    dark = min(luminance(left), luminance(right))
    return (light + 0.05) / (dark + 0.05)


def _chroma(colors: dict[str, str], bg: str) -> list[tuple[str, float, float, float]]:
    """Saturated swatches that still read on this background: hex, sat, lum, contrast."""
    found: dict[str, tuple[str, float, float, float]] = {}
    for key, value in colors.items():
        if _color_key(key) in _STRUCTURAL:
            continue
        sat = saturation(value)
        lum = luminance(value)
        if sat < 0.12 or lum < 0.25:
            continue
        contrast = contrast_ratio(value, bg)
        if contrast < 3.0:
            continue
        hex_key = value.lower()
        row = (hex_key, sat, lum, contrast)
        prev = found.get(hex_key)
        if prev is None or sat > prev[1]:
            found[hex_key] = row
    return list(found.values())


def pick_accent_peak(colors: dict[str, str], bg: str) -> tuple[str, str]:
    """Peak is the lightest chromatic swatch; accent is the next that still reads.

    Named `accent` on spacex-terrafab is a dull slate while cyan and ice sit
    unused. Rank by luminance so those lights become the meter peak and the
    accent. A theme that only ships slate and mauve keeps slate as the accent.
    """
    rows = _chroma(colors, bg)
    fallback_accent = colors.get("accent") or colors.get("blue") or colors.get("green") or FALLBACK.accent
    fallback_peak = colors.get("orange") or colors.get("yellow") or fallback_accent
    if not rows:
        return fallback_accent, fallback_peak
    peak = max(rows, key=lambda row: (row[2], row[3], row[1]))[0]
    rest = [row for row in rows if row[0] != peak and row[2] <= 0.86]
    if not rest:
        rest = [row for row in rows if row[0] != peak]
    if not rest:
        return peak, peak
    accent = max(rest, key=lambda row: (row[2], row[3], row[1]))[0]
    return accent, peak


def palette_from_colors(colors: dict[str, str]) -> Palette:
    bg = colors.get("background") or colors.get("bg") or FALLBACK.bg
    fg = colors.get("foreground") or colors.get("fg") or FALLBACK.fg
    muted = colors.get("muted") or colors.get("dark_fg") or FALLBACK.muted
    accent, peak = pick_accent_peak(colors, bg)
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


def apply_color_overrides(palette: Palette, overrides: dict[str, str] | None) -> Palette:
    chosen = overrides or {}
    accent = chosen.get("accent") or palette.accent
    peak = chosen.get("peak") or palette.peak
    if accent == palette.accent and peak == palette.peak:
        return palette
    return Palette(
        name=palette.name,
        bg=palette.bg,
        panel=palette.panel,
        fg=palette.fg,
        muted=palette.muted,
        accent=accent,
        peak=peak,
        highlight=mix_hex(palette.bg, accent, 0.34),
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
            font-family: "JetBrains Mono", "Space Grotesk", monospace;
            border-radius: 0;
            box-shadow: none;
        }}
        headerbar {{
            background: {palette.bg};
            padding: 8px 16px;
            min-height: 36px;
            border-bottom: 1px solid {mix_hex(palette.bg, palette.muted, 0.4)};
        }}
        .stage {{
            background: {palette.bg};
        }}
        .deck {{
            background: {palette.bg};
            border: 1px solid {mix_hex(palette.bg, palette.muted, 0.45)};
        }}
        /* Short tiles (fit_deck compact): tighter bars and a smaller LCD. */
        .deck.deck-compact .deck-bar, .deck.deck-compact .foot {{
            padding: 4px 14px;
            min-height: 28px;
        }}
        .deck.deck-compact .lcd {{
            padding: 10px 18px 6px;
        }}
        .deck.deck-compact .marquee {{
            font-size: 26px;
        }}
        .deck.deck-compact .clock {{
            font-size: 22px;
        }}
        .deck.deck-compact .transport {{
            padding: 6px 16px;
        }}
        /* Thin tiles (fit_deck narrow): a tighter transport row. */
        .deck.deck-narrow .transport {{
            padding-left: 10px;
            padding-right: 10px;
        }}
        .deck.deck-narrow button.tb {{
            min-width: 36px;
        }}
        .vol-num {{
            color: {palette.accent};
            font-size: 18px;
            min-width: 2em;
        }}
        .deck-bar, .foot {{
            padding: 10px 18px;
            min-height: 40px;
        }}
        .deck-bar {{
            border-bottom: 1px solid {mix_hex(palette.bg, palette.muted, 0.4)};
        }}
        .deck-bar button.home-link {{
            min-height: 0;
            min-width: 0;
            padding: 0;
        }}
        .wordmark {{
            letter-spacing: 0.22em;
            font-size: 11px;
            color: {palette.fg};
            text-transform: uppercase;
        }}
        .home-link {{
            letter-spacing: 0.24em;
            font-size: 10px;
            color: {palette.muted};
        }}
        .chrome {{
            background: {palette.panel};
            padding: 8px 12px;
        }}
        .lcd {{
            background: {mix_hex(palette.bg, "#000000", 0.45)};
            padding: 18px 22px 10px;
            border-bottom: 1px solid {mix_hex(palette.bg, palette.muted, 0.4)};
        }}
        .marquee {{
            color: {palette.accent};
            font-size: 36px;
            font-weight: 400;
            letter-spacing: 0.04em;
        }}
        .artist {{
            letter-spacing: 0.18em;
            font-size: 11px;
            color: {mix_hex(palette.muted, palette.accent, 0.35)};
            text-transform: uppercase;
        }}
        .clock {{
            color: {palette.accent};
            font-size: 28px;
        }}
        .dur {{
            color: {palette.muted};
            font-size: 16px;
        }}
        .transport {{
            padding: 12px 20px;
            border-bottom: 1px solid {mix_hex(palette.bg, palette.muted, 0.4)};
        }}
        button.tb {{
            min-width: 44px;
            min-height: 36px;
            border-radius: 0;
            margin-left: -1px;
            color: {palette.fg};
            background: {palette.bg};
            border: 1px solid {mix_hex(palette.bg, palette.muted, 0.5)};
        }}
        button.mark {{
            font-size: 9px;
            letter-spacing: 0.14em;
            padding: 0 8px;
        }}
        .knob-lbl, .find-l, .find-k {{
            letter-spacing: 0.18em;
            font-size: 9px;
            color: {palette.muted};
        }}
        .find-k {{
            border: 1px solid {mix_hex(palette.bg, palette.muted, 0.4)};
            padding: 2px 6px;
        }}
        entry.find-i {{
            background: transparent;
            border: none;
            min-height: 28px;
        }}
        button.seg {{
            letter-spacing: 0.22em;
            font-size: 10px;
            min-height: 28px;
            border-radius: 0;
            background: transparent;
            color: {palette.muted};
        }}
        button.seg:checked {{
            background: {palette.accent};
            color: {palette.bg};
            border-color: {palette.accent};
        }}
        .foot {{
            border-top: 1px solid {mix_hex(palette.bg, palette.muted, 0.4)};
        }}
        .pulse {{
            color: {palette.accent};
        }}
        .pulse-off {{
            color: {palette.muted};
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
        .foot-note, .foot-progress, .foot-reconnect {{
            color: {palette.muted};
        }}
        .foot-error, .foot-offline, .foot-session {{
            color: {palette.peak};
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
        button.play {{
            min-width: 74px;
            background: {palette.accent};
            color: {palette.bg};
            border-color: {palette.accent};
        }}
        button.play:hover {{
            background: {palette.peak};
            border-color: {palette.peak};
            color: {palette.bg};
        }}
        button:hover {{
            border-color: {palette.accent};
            color: {palette.accent};
        }}
        button.play:hover {{
            color: {palette.bg};
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
        button.rate:checked {{
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
