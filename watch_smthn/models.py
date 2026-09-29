"""Data models for channels, players, and categories."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PlayerType(Enum):
    MPV = "mpv"
    VLC = "vlc"
    FFPLAY = "ffplay"
    IPTV = "iptv"
    SLING = "sling"
    PLEX = "plex"
    WEB = "web"
    CUSTOM = "custom"


class ContentType(Enum):
    LIVE_TV = "Live TV"
    MOVIES = "Movies"
    SERIES = "Series"
    SPORTS = "Sports"
    NEWS = "News"
    MUSIC = "Music"
    KIDS = "Kids"
    DOCUMENTARY = "Documentary"
    EDUCATION = "Education"
    COMEDY = "Comedy"
    CULTURE = "Culture"
    RELAX = "Relax"
    RELIGIOUS = "Religious"
    LIFESTYLE = "Lifestyle"
    OTHER = "Other"


@dataclass
class Player:
    name: str
    player_type: PlayerType
    command: list[str] = field(default_factory=list)
    args: list[str] = field(default_factory=list)
    url_template: Optional[str] = None
    is_default: bool = False

    def build_command(self, url: str) -> list[str]:
        if self.player_type in (PlayerType.MPV, PlayerType.VLC, PlayerType.FFPLAY):
            return [self.command[0], *self.args, url] if self.command else []
        if self.player_type == PlayerType.WEB:
            return ["xdg-open", url]
        if self.player_type == PlayerType.CUSTOM and self.command:
            return [*self.command, url]
        return [self.player_type.value, url]


@dataclass(frozen=True)
class EntryMeta:
    """User-supplied row metadata for one entry of a source's ``urls``.

    One field per table column (Name / Group / Country). ``None`` means "no
    override", so the parser keeps whatever the file itself supplied.
    ``country`` is stored verbatim -- ``tvg-country`` is not always a code --
    and the ``country:`` search param matches exactly, so callers should pass
    codes such as ``PH`` rather than country names.
    """

    title: str | None = None
    group: str | None = None
    country: str | None = None


@dataclass
class Channel:
    name: str
    url: str
    logo: str = ""
    group: str = ""
    content_type: ContentType = ContentType.OTHER
    country: str = ""
    language: str = ""
    tvg_id: str = ""
    tvg_name: str = ""
    favorite: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        return self.name

    @property
    def label(self) -> str:
        parts = [self.name]
        if self.group:
            parts.append(f"[{self.group}]")
        return " ".join(parts)


@dataclass
class Playlist:
    name: str
    source: str  # file path or URL
    channels: list[Channel] = field(default_factory=list)
    is_remote: bool = False
