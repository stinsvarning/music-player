# Compact native music-player UI

Date: 2026-08-14

## Goal

Restyle the existing GTK4 player so it feels like a compact Omarchy utility: dense, glanceable, about the same size as today, and painted from the active Omarchy theme. Playback, mix, queue, and seek stay as they are.

## Locked decisions

- Compact utility (~920×720 Hyprland float, class `stream.music.Player`).
- Omarchy-native GTK. Live theme reload from `~/.config/omarchy/current/theme/colors.toml`.
- Layout: header → now-playing + transport → thin spectrum → Queue / Equalizer / Music. Status line under the lists, not a chrome footer bar.
- GTK4 only. Engine / IPC unchanged.

## Layout

1. Native `Gtk.HeaderBar`: title `Music`, subtitle, `?` shortcuts. No swatches.
2. Now playing + transport in one block: 96×96 art, title/artist, seek, symbolic transport, shuffle/repeat/Play-similar icons, volume.
3. Spectrum, 36-bar renderer, `bands` from an in-memory cache (engine samples only while the UI is asking).
4. Tabs unchanged in behavior. Playing vs selected colors restyled only.
5. Status hints are a muted line on the Music/Queue chrome, not a second title bar.

## Theme

Map `colors.toml` into `Palette`. If `selection_background` is too light (luminance ≥ 0.45), mix `accent` onto `bg` for the playing-row fill. Missing file → dark neutral fallback, not mint.

Watch `~/.config/omarchy/current` and `colors.toml`. Debounce 150ms. Failed reload keeps last CSS.

## Out of scope

Engine internals, RADIO, lyrics, libadwaita. MPRIS is on the engine (`org.mpris.MediaPlayer2.Music`).
