from __future__ import annotations

from dataclasses import dataclass

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk, Pango

# Design size of the deck card (content box) and its 1px CSS border on each side.
DECK_W = 1180
DECK_H = 800
DECK_FRAME = 2
# Room kept between the card and the window edge when the card has to shrink.
DECK_MARGIN = 24
# Below these the card fills the window edge to edge instead of keeping a margin.
DECK_FILL_W = 900
DECK_FILL_H = 600
# Card sizes that switch to the tighter layouts.
COMPACT_H = 700
NARROW_W = 900


@dataclass(frozen=True)
class DeckFit:
    width: int
    height: int
    compact: bool  # short: smaller LCD and bars
    narrow: bool  # thin: tighter transport row


def fit_deck(win_w: int, win_h: int) -> DeckFit:
    """Outer deck size for a window. Never larger than the design size, so a big
    window (fullscreen 3840x1600) keeps the exact 1180x800 card; smaller tiles
    shrink the card to fit with a margin, or edge to edge when very small."""
    full_w, full_h = DECK_W + DECK_FRAME, DECK_H + DECK_FRAME
    w = max(min(full_w, win_w - 2 * DECK_MARGIN), min(win_w, DECK_FILL_W))
    h = max(min(full_h, win_h - 2 * DECK_MARGIN), min(win_h, DECK_FILL_H))
    w, h = max(1, min(w, full_w)), max(1, min(h, full_h))
    return DeckFit(w, h, compact=h < COMPACT_H, narrow=w < NARROW_W)


def bind_ellipsize(label: Gtk.Label, chars: int, *, hexpand: bool = True) -> Gtk.Label:
    """Keep long titles from driving the window's natural width."""
    label.set_ellipsize(Pango.EllipsizeMode.END)
    label.set_max_width_chars(chars)
    label.set_hexpand(hexpand)
    label.set_halign(Gtk.Align.FILL)
    label.set_size_request(1, -1)
    return label


def caption_bar() -> tuple[Gtk.Box, Gtk.Box, Gtk.Box]:
    """Shared strip under the tab labels; two columns match the page split."""
    bar = Gtk.Box(spacing=8)
    bar.add_css_class("tab-caption")
    bar.set_hexpand(True)
    left = Gtk.Box()
    left.set_hexpand(True)
    left.set_valign(Gtk.Align.CENTER)
    right = Gtk.Box()
    right.set_hexpand(True)
    right.set_valign(Gtk.Align.CENTER)
    bar.append(left)
    bar.append(right)
    return bar, left, right


def constrain_scroll(scroll: Gtk.ScrolledWindow) -> Gtk.ScrolledWindow:
    scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scroll.set_propagate_natural_width(False)
    scroll.set_propagate_natural_height(False)
    scroll.set_hexpand(True)
    scroll.set_vexpand(True)
    scroll.set_margin_bottom(8)
    return scroll


def make_row(left: str, mid: str, right: str) -> Gtk.ListBoxRow:
    row = Gtk.ListBoxRow()
    box = Gtk.Box(spacing=12)
    box.set_margin_start(8)
    box.set_margin_end(8)
    box.set_margin_top(5)
    box.set_margin_bottom(5)
    a = Gtk.Label(label=left, xalign=0)
    bind_ellipsize(a, 36)
    b = Gtk.Label(label=mid, xalign=0)
    b.add_css_class("meta")
    bind_ellipsize(b, 16, hexpand=False)
    b.set_width_chars(10)
    c = Gtk.Label(label=right, xalign=1)
    c.add_css_class("meta")
    c.set_width_chars(5)
    box.append(a)
    box.append(b)
    box.append(c)
    row.set_child(box)
    return row


def clear_list(widget: Gtk.ListBox) -> None:
    child = widget.get_first_child()
    while child is not None:
        nxt = child.get_next_sibling()
        widget.remove(child)
        child = nxt
