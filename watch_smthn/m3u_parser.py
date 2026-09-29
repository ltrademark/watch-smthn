"""M3U/M3U8 playlist parser."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional
from urllib.request import urlopen

from .models import Channel, ContentType, EntryMeta, Playlist


EXTINF_RE = re.compile(r'^#EXTINF:(-?\d+)\s*(.*)$', re.DOTALL)
ATTR_RE = re.compile(r'([\w-]+)=["\']([^"\']*)["\']')
HLS_TAG_RE = re.compile(r'^#EXT-X-', re.MULTILINE)


def _parse_content_type(group: str) -> ContentType:
    g = group.lower()
    mapping = {
        ContentType.LIVE_TV: ("live", "tv", "channel", "news"),
        ContentType.MOVIES: ("movie", "film", "cinema"),
        ContentType.SERIES: ("series", "show", "episode"),
        ContentType.SPORTS: ("sport", "espn", "fox sport", "nfl", "nba"),
        ContentType.NEWS: ("news", "cnn", "bbc", "fox news"),
        ContentType.MUSIC: ("music", "mtv", "vh1"),
        ContentType.KIDS: ("kid", "child", "cartoon", "nick", "animation"),
        ContentType.DOCUMENTARY: ("docu", "discovery", "nat geo"),
        ContentType.EDUCATION: ("education", "learn", "school"),
        ContentType.COMEDY: ("comedy"),
        ContentType.CULTURE: ("culture"),
        ContentType.RELAX: ("relax", "travel", "outdoor"),
        ContentType.RELIGIOUS: ("religious", "faith"),
        ContentType.LIFESTYLE: ("lifestyle", "cooking", "family"),
    }
    for ct, keywords in mapping.items():
        if any(k in g for k in keywords):
            return ct
    return ContentType.OTHER


def _extract_country_from_tvg_id(tvg_id: str) -> str:
    """Extract country code from tvg-id like 'ChannelName.us@SD' -> 'US'."""
    if "@" in tvg_id:
        base = tvg_id.split("@")[0]
    else:
        base = tvg_id
    parts = base.rsplit(".", 1)
    if len(parts) == 2 and len(parts[1]) <= 3:
        return parts[1].upper()
    return ""


def _split_extinf(line: str) -> tuple[str, str]:
    """Split EXTINF line into attributes string and display name.

    The display name comes after the last comma that is NOT inside quotes.
    """
    body = line[len("#EXTINF:"):]
    in_quote = False
    quote_char = ""
    last_comma_outside = -1
    for i, ch in enumerate(body):
        if in_quote:
            if ch == quote_char:
                in_quote = False
        else:
            if ch in ('"', "'"):
                in_quote = True
                quote_char = ch
            elif ch == ",":
                last_comma_outside = i
    if last_comma_outside >= 0:
        return body[:last_comma_outside], body[last_comma_outside + 1:].strip()
    return body, ""


def parse_m3u_content(content: str, playlist_name: str = "") -> Playlist:
    lines = content.strip().splitlines()
    channels: list[Channel] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF:"):
            attrs_str, display_name = _split_extinf(line)
            attrs = dict(ATTR_RE.findall(attrs_str))
            group_raw = attrs.get("group-title", "")
            group = group_raw.split(";")[0].strip() if group_raw else ""
            logo = attrs.get("tvg-logo", "")
            tvg_id = attrs.get("tvg-id", "")
            tvg_name = attrs.get("tvg-name", "")
            country = attrs.get("tvg-country", "") or _extract_country_from_tvg_id(tvg_id)
            language = attrs.get("tvg-language", "")
            # next non-empty, non-comment line is the URL
            i += 1
            url = ""
            while i < len(lines):
                candidate = lines[i].strip()
                if candidate and not candidate.startswith("#"):
                    url = candidate
                    break
                i += 1
            if url:
                channels.append(Channel(
                    name=display_name or tvg_name or url.split("/")[-1],
                    url=url,
                    logo=logo,
                    group=group,
                    content_type=_parse_content_type(group_raw),
                    country=country,
                    language=language,
                    tvg_id=tvg_id,
                    tvg_name=tvg_name,
                ))
        i += 1
    return Playlist(name=playlist_name, source="inline", channels=channels)


def _is_hls(content: str) -> bool:
    """True when the body is an HLS playlist rather than a channel list.

    ``#EXT-X-`` is the HLS-only tag namespace (RFC 8216), so channel lists --
    which use ``#EXTM3U``/``#EXTINF``/``#EXTGRP``/``#EXTVLCOPT``/``#KODIPROP``
    -- can never match it. Detection is deliberately content-based: plenty of
    channel lists are served from ``.m3u8`` URLs.
    """
    return bool(HLS_TAG_RE.search(content))


def _stream_playlist(
    locator: str, name: str, meta: EntryMeta | None = None
) -> Playlist:
    """Collapse an HLS playlist into one row that points at the playlist itself.

    Players fetch the playlist and pull the segments themselves, which is what
    every browser does with these. Emitting a row per segment instead yields
    relative ``.ts`` URLs that cannot resolve and cannot be played.

    ``meta.title`` renames the row and ``meta.country`` fills the country
    column; neither has a file to inherit from, so both come straight from
    ``meta``. The group defaults to the source name only when that would not
    duplicate the row's own name -- the name *is* the source name when the row
    is untitled, and a titled row can name the source itself -- otherwise the
    two columns would repeat the same string. An explicit ``meta.group``
    always wins.
    """
    meta = meta or EntryMeta()
    row_name = meta.title or name
    group = meta.group or ("" if row_name == name else name)
    return Playlist(name=name, source=locator, channels=[Channel(
        name=row_name,
        url=locator,
        group=group,
        country=meta.country or "",
        extra={"source": name, "direct": True, "hls": True},
    )])


def _apply_overrides(playlist: Playlist, meta: EntryMeta | None) -> Playlist:
    """Apply ``meta`` to every row of a multi-row playlist.

    The rows keep the names the file gave them -- retitling each one would
    collapse them all to the same string -- so ``meta.title`` is spent on the
    group instead, surfacing as a sidebar category. ``meta.group`` outranks
    that, and ``meta.country`` replaces the file's own country.

    Everything is applied unconditionally so input the user typed is never
    silently dropped, including in place of a ``group-title`` or
    ``tvg-country`` the file already supplied. As a consequence ``title`` has
    nothing left to do when ``group`` is also set, and is ignored there.
    """
    meta = meta or EntryMeta()
    for channel in playlist.channels:
        if meta.group:
            channel.group = meta.group
        elif meta.title:
            channel.group = meta.title
        if meta.country:
            channel.country = meta.country
    return playlist


def load_playlist(path: str, name: str = "", meta: EntryMeta | None = None) -> Playlist:
    p = Path(path)
    if not name:
        name = p.stem
    content = p.read_text(encoding="utf-8", errors="replace")
    if _is_hls(content):
        return _stream_playlist(str(p), name, meta)
    return _apply_overrides(parse_m3u_content(content, playlist_name=name), meta)


def load_remote_playlist(
    url: str, name: str = "", meta: EntryMeta | None = None
) -> Playlist:
    if not name:
        name = url.split("/")[-1].split("?")[0] or "Remote"
    with urlopen(url, timeout=15) as resp:
        content = resp.read().decode("utf-8", errors="replace")
    if _is_hls(content):
        return _stream_playlist(url, name, meta)
    return _apply_overrides(parse_m3u_content(content, playlist_name=name), meta)


def load_playlist_auto(
    source: str, name: str = "", meta: EntryMeta | None = None
) -> Playlist:
    if source.startswith("http://") or source.startswith("https://"):
        return load_remote_playlist(source, name, meta)
    return load_playlist(source, name, meta)
