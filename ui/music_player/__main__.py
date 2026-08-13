from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from .app import MusicApplication


def main() -> int:
    return MusicApplication().run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
