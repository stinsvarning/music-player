from __future__ import annotations

import cairo
import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk

from music_player.spectrum import (
    BRICK_COLS,
    VIS_MODES,
    FramePacer,
    LcdState,
    bar_index_at,
    brick_columns,
    normalize_vis,
)
from music_player.theme import Palette, palette_named
from music_player.widgets.vis_paint import paint_lcd


class SpectrumView(Gtk.DrawingArea):
    """The LCD strip. Bands arrive at engine rate; bricks and wave ease per frame."""

    def __init__(self) -> None:
        super().__init__()
        self.set_hexpand(True)
        self.set_content_height(84)
        self.mode = VIS_MODES[0]
        self.on_cycle = None
        self.state = LcdState()
        self._bands = [0.0] * 10
        self._cols = [0] * BRICK_COLS
        self._hover = -1
        self._last_frame = 0
        self._awake = False
        self._pacer = FramePacer()  # 60 fps cap, even on a 120 Hz monitor
        self.palette: Palette = palette_named("mint")
        self.set_draw_func(self._draw)
        self.set_cursor_from_name("pointer")
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", lambda *_a: self._set_hover(-1))
        self.add_controller(motion)
        click = Gtk.GestureClick()
        click.connect("released", self._on_click)
        self.add_controller(click)
        self._tick_id = 0
        self._wake()

    def _wake(self) -> None:
        """Run the per-frame animation; it removes itself again once everything settles,
        so a paused or stopped player does not keep the frame clock running."""
        if not self._tick_id:
            self._last_frame = 0
            self._tick_id = self.add_tick_callback(self._on_tick)

    def set_mode(self, mode: str) -> None:
        self.mode = normalize_vis(mode)
        self.queue_draw()

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette
        self.queue_draw()

    def set_volume(self, volume: float | None) -> None:
        self.state.set_volume(volume)

    def set_bands(self, bands: list[float]) -> None:
        self.state.set_bands(bands)
        self._bands = list(self.state.target)
        self._cols = brick_columns(self._bands)
        if any(v > 1e-3 for v in self._bands) and not self._awake:
            self._awake = True
            self._pacer.reset()
            self._wake()
        if self.mode == "waterfall":
            self.queue_draw()

    def _on_tick(self, _widget, clock) -> bool:
        now = clock.get_frame_time()
        dt = (now - self._last_frame) / 1_000_000 if self._last_frame else 0.0
        self._last_frame = now
        if not self._awake:
            self._tick_id = 0
            return False  # removed; set_bands adds it back when sound returns
        step = self._pacer.step(dt)
        if step is None:
            return True  # skip this refresh; the next one catches up the time
        active = self.state.advance(step)
        if self.mode != "waterfall":
            self.queue_draw()
        if not active:
            self._awake = False  # everything has settled; stop redrawing until new bands
        return True

    def _on_click(self, *_a) -> None:
        if callable(self.on_cycle):
            self.on_cycle()

    def _on_motion(self, _c, x, _y) -> None:
        self._set_hover(bar_index_at(x, self.get_width(), len(self._cols)))

    def _set_hover(self, idx: int) -> None:
        if idx == self._hover:
            return
        self._hover = idx
        self.queue_draw()

    def _draw(self, _area: Gtk.DrawingArea, cr: cairo.Context, width: int, height: int) -> None:
        paint_lcd(cr, width, height, self.mode, self.palette, self.state, self._hover)
