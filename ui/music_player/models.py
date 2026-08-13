from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
    eq_preset: str = "Flat"
    eq_bands: list[float] = field(default_factory=lambda: [0.0] * 10)
    track: Track | None = None


class SeekGate:
    def __init__(self) -> None:
        self._pending: float | None = None

    def drag(self, target: float) -> None:
        self._pending = float(target)

    def release(self, *, current: float) -> float | None:
        if self._pending is None:
            return None
        target = self._pending
        self._pending = None
        return target


def format_time(seconds: float | int | None) -> str:
    if not seconds:
        return "0:00"
    total = max(0, int(seconds))
    return f"{total // 60}:{total % 60:02d}"


def parse_track(obj: dict[str, Any] | None) -> Track | None:
    if not obj:
        return None
    tid = obj.get("id") or ""
    path = obj.get("path") or (f"https://music.youtube.com/watch?v={tid}" if tid else "")
    return Track(
        id=str(tid),
        title=obj.get("title") or tid,
        artist=obj.get("artist") or "",
        album=obj.get("album") or "",
        duration_secs=int(obj.get("duration_secs") or 0),
        path=path,
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
        eq_preset=payload.get("eq_preset") or "Flat",
        eq_bands=bands,
        track=parse_track(payload.get("track")),
    )


def parse_tracks(payload: dict[str, Any] | list) -> list[Track]:
    items = payload if isinstance(payload, list) else payload.get("tracks") or []
    out = []
    for item in items:
        track = parse_track(item)
        if track and track.id:
            out.append(track)
    return out


def parse_playlists(payload: dict[str, Any] | list) -> list[PlaylistInfo]:
    items = payload if isinstance(payload, list) else payload.get("playlists") or []
    out = []
    for item in items:
        pid = item.get("id") or ""
        if not pid:
            continue
        out.append(PlaylistInfo(id=str(pid), name=str(item.get("name") or pid), track_count=int(item.get("track_count") or 0)))
    return out


def art_url_for(track: Track | None) -> str:
    if not track or not track.id:
        return ""
    return f"https://i.ytimg.com/vi/{track.id}/hqdefault.jpg"
