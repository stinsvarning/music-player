from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any


class BrowseState:
    """MUSIC tab: search results must not block playlist browsing."""

    def __init__(self) -> None:
        self.search_tracks: list[Track] | None = None
        self.lib_tracks: list[Track] = []
        self.generation = 0

    def visible(self) -> list[Track]:
        return self.search_tracks if self.search_tracks is not None else self.lib_tracks

    def begin_search(self) -> int:
        self.generation += 1
        return self.generation

    def finish_search(self, gen: int, tracks: list[Track], *, append: bool = False) -> bool:
        if gen != self.generation:
            return False
        if append:
            if self.search_tracks is None:
                self.search_tracks = []
            self.search_tracks.extend(tracks)
        else:
            self.search_tracks = list(tracks)
        return True

    def select_playlist(self) -> int:
        self.search_tracks = None
        self.generation += 1
        return self.generation

    def open_playlist(self) -> int:
        """Leave search and drop stale rows so activate cannot hit the wrong track."""
        self.lib_tracks = []
        return self.select_playlist()

    def finish_playlist(self, gen: int, tracks: list[Track], *, append: bool = False) -> bool:
        if gen != self.generation:
            return False
        if append:
            self.lib_tracks.extend(tracks)
        else:
            self.lib_tracks = list(tracks)
        self.search_tracks = None
        return True


@dataclass
class Track:
    id: str = ""
    title: str = ""
    artist: str = ""
    album: str = ""
    duration_secs: int = 0
    path: str = ""

    def to_ipc(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "duration_secs": self.duration_secs,
            "path": self.path,
        }


@dataclass
class PlaylistInfo:
    id: str
    name: str
    track_count: int = 0


@dataclass
class PlayerStatus:
    state: str = "stopped"
    position: float = 0.0
    duration: float = 0.0
    volume: float = 70.0
    index: int = -1
    total: int = 0
    shuffle: bool = False
    repeat: str = "off"
    automix: bool = False
    sleep_remaining: int = 0
    sleep_minutes: int = 0
    eq_preset: str = "Flat"
    eq_bands: list[float] = field(default_factory=lambda: [0.0] * 10)
    track: Track | None = None
    logged_in: bool = False
    auth_source: str = ""


class SeekGate:
    """Hold the slider until the gesture settles, then emit absolute seconds.

    GTK4 Scale often swallows GestureClick release, so callers also poll
    ``take_settled``. After a commit, ``follow_status`` stays false briefly so
    a stale status poll cannot snap the bar back.
    """

    def __init__(self, settle_s: float = 0.12, ignore_s: float = 0.45) -> None:
        self._pending: float | None = None
        self._changed_at: float = 0.0
        self._ignore_until: float = 0.0
        self._settle_s = settle_s
        self._ignore_s = ignore_s

    def drag(self, target: float, *, now: float | None = None) -> None:
        self._pending = float(target)
        self._changed_at = time.monotonic() if now is None else now

    def release(self, *, current: float | None = None, now: float | None = None) -> float | None:
        del current  # absolute seek; kept for older call sites
        if self._pending is None:
            return None
        return self._commit(now)

    def take_settled(self, *, now: float | None = None) -> float | None:
        if self._pending is None:
            return None
        stamp = time.monotonic() if now is None else now
        if stamp - self._changed_at < self._settle_s:
            return None
        return self._commit(stamp)

    def follow_status(self, *, now: float | None = None) -> bool:
        if self._pending is not None:
            return False
        stamp = time.monotonic() if now is None else now
        return stamp >= self._ignore_until

    def _commit(self, now: float | None) -> float:
        target = float(self._pending or 0.0)
        self._pending = None
        stamp = time.monotonic() if now is None else now
        self._ignore_until = stamp + self._ignore_s
        return target


def queue_needs_rebuild(old_ids: list[str], new_ids: list[str]) -> bool:
    return list(old_ids) != list(new_ids)


def default_queue_playlist_name(when: date | None = None) -> str:
    day = when or date.today()
    return f"Queue {day.isoformat()}"


def song_menu_actions(source: str) -> list[str]:
    actions = ["Start mix"]
    if source != "queue":
        actions.extend(["Play next", "Add to queue"])
    actions.append("Save this track…")
    if source == "queue":
        actions.extend(["Save entire queue…", "Remove"])
    return actions


def format_time(seconds: float | int | None) -> str:
    if not seconds:
        return "0:00"
    total = max(0, int(seconds))
    return f"{total // 60}:{total % 60:02d}"


def _plain(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str) and text:
            return text
        runs = value.get("runs") or []
        parts = []
        for run in runs:
            if isinstance(run, str):
                parts.append(run)
            elif isinstance(run, dict) and run.get("text"):
                parts.append(str(run["text"]))
        if parts:
            return "".join(parts)
        name = value.get("name")
        if isinstance(name, str) and name:
            return name
    return ""


def parse_track(obj: dict[str, Any] | None) -> Track | None:
    if not obj:
        return None
    tid = _plain(obj.get("id"))
    path = _plain(obj.get("path")) or (f"https://music.youtube.com/watch?v={tid}" if tid else "")
    return Track(
        id=tid,
        title=_plain(obj.get("title")) or tid,
        artist=_plain(obj.get("artist")),
        album=_plain(obj.get("album")),
        duration_secs=int(obj.get("duration_secs") or 0),
        path=path,
    )


def can_autoselect_playlist(*, first: bool, searching: bool) -> bool:
    return bool(first) and not searching


def tracks_caption(*, query: str = "", playlist_name: str = "") -> str:
    q = (query or "").strip()
    if q:
        return f"SEARCH · {q}"
    name = (playlist_name or "").strip()
    return name.upper() if name else "TRACKS"


def current_lyric_index(lines: list[dict] | None, position: float, duration: float) -> int:
    rows = list(lines or [])
    if not rows:
        return -1
    pos = float(position or 0.0)
    timed = any(row.get("start") is not None for row in rows)
    if timed:
        idx = 0
        for i, row in enumerate(rows):
            start = row.get("start")
            if start is not None and pos >= float(start):
                idx = i
        return idx
    dur = float(duration or 0.0)
    if dur <= 0:
        return 0
    sung = [i for i, row in enumerate(rows) if str(row.get("text") or "").strip()]
    if not sung:
        return -1
    start = min(12.0, dur * 0.15)
    end = max(start, dur - min(10.0, dur * 0.12))
    if pos < start:
        return -1
    if pos >= end:
        return sung[-1]
    span = end - start
    if span <= 0:
        return sung[0]
    slot = min(len(sung) - 1, max(0, int((pos - start) / span * len(sung))))
    return sung[slot]


def is_login_error(text: str) -> bool:
    low = (text or "").lower()
    return "login_required" in low or "no youtube cookies" in low or (
        "cookie" in low and any(tok in low for tok in ("expired", "invalid", "sign in", "login"))
    )


def parse_status(payload: dict[str, Any]) -> PlayerStatus:
    bands = [float(x) for x in (payload.get("eq_bands") or [])[:10]]
    while len(bands) < 10:
        bands.append(0.0)
    return PlayerStatus(
        state=payload.get("state") or "stopped",
        position=float(payload.get("position") or 0.0),
        duration=float(payload.get("duration") or 0.0),
        volume=float(payload.get("volume") if payload.get("volume") is not None else 70),
        index=int(payload.get("index") if payload.get("index") is not None else -1),
        total=int(payload.get("total") or 0),
        shuffle=bool(payload.get("shuffle")),
        repeat=str(payload.get("repeat") or "off"),
        automix=bool(payload.get("automix")),
        sleep_remaining=int(payload.get("sleep_remaining") or 0),
        sleep_minutes=int(payload.get("sleep_minutes") or 0),
        eq_preset=payload.get("eq_preset") or "Flat",
        eq_bands=bands,
        track=parse_track(payload.get("track")),
        logged_in=bool(payload.get("logged_in")),
        auth_source=str(payload.get("auth_source") or payload.get("source") or ""),
    )


def parse_tracks(payload: dict[str, Any] | list) -> list[Track]:
    items = payload if isinstance(payload, list) else payload.get("tracks") or []
    out = []
    for item in items:
        track = parse_track(item)
        if track and track.id:
            out.append(track)
    return out


def page_done(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return True
    return payload.get("done", True) is not False


def parse_playlists(payload: dict[str, Any] | list) -> list[PlaylistInfo]:
    items = payload if isinstance(payload, list) else payload.get("playlists") or []
    out = []
    for item in items:
        pid = _plain(item.get("id"))
        if not pid:
            continue
        out.append(
            PlaylistInfo(
                id=pid,
                name=_plain(item.get("name")) or pid,
                track_count=int(item.get("track_count") or 0),
            )
        )
    return out


def art_url_for(track: Track | None) -> str:
    if not track or not track.id:
        return ""
    return f"https://i.ytimg.com/vi/{track.id}/hqdefault.jpg"
