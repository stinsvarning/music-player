-- Optional Omarchy/Hyprland bind: same action as clicking the Music bar chip.
-- SUPER+SHIFT+M is Omarchy's default Music key (Spotify). Unbind it first.
--
-- In ~/.config/hypr/bindings.lua:
--   require("hypr.music-player-bindings")
-- after you copy this file to ~/.config/hypr/music-player-bindings.lua
-- or paste the two lines below.

hl.unbind("SUPER + SHIFT + M")
o.bind("SUPER + SHIFT + M", "Music", 'omarchy launch or focus "^stream\\.music\\.Player$" music-player')
