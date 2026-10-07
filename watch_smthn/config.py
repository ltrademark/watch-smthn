"""Configuration loader for watch somethin."""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import yaml

from .models import Channel, ContentType, EntryMeta, Player, PlayerType

CONFIG_DIRS = [
    Path.home() / ".config" / "watch-smthn",
    Path.home() / ".watch-smthn",
]
CONFIG_FILE_NAMES = ["config.yaml", "config.yml", "config.json"]

BUNDLED_CONFIG = Path(__file__).parent / "data" / "default_config.yaml"

RESERVED_SOURCE_NAMES = {"iptv"}


def _find_config() -> Path | None:
    for d in CONFIG_DIRS:
        for name in CONFIG_FILE_NAMES:
            p = d / name
            if p.exists():
                return p
    return None


def _load_config_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(text) or {}
    return json.loads(text)


def load_config() -> dict[str, Any]:
    p = _find_config()
    if p:
        return _load_config_file(p)
    if BUNDLED_CONFIG.exists():
        return _load_config_file(BUNDLED_CONFIG)
    return {}


def get_custom_players(config: dict[str, Any]) -> list[Player]:
    players = []
    for entry in config.get("players", []):
        pt = PlayerType(entry.get("type", "custom"))
        players.append(Player(
            name=entry.get("name", "Custom"),
            player_type=pt,
            command=entry.get("command", []),
            args=entry.get("args", []),
            url_template=entry.get("url_template"),
            is_default=entry.get("default", False),
        ))
    return players


def get_player_paths(config: dict[str, Any]) -> dict[str, str]:
    raw = config.get("player_paths")
    if not isinstance(raw, dict):
        return {}
    paths: dict[str, str] = {}
    for key, value in raw.items():
        name = str(key).strip()
        target = "" if value is None else str(value).strip()
        if name and target:
            paths[name] = target
    return paths


def get_editor(config: dict[str, Any]) -> str | None:
    value = config.get("editor")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _entry_meta(item: dict[str, Any]) -> EntryMeta:
    """Build an :class:`EntryMeta` from a ``urls`` mapping, blanks meaning absent."""
    def opt(key: str) -> str | None:
        return str(item.get(key, "") or "").strip() or None

    return EntryMeta(title=opt("title"), group=opt("group"), country=opt("country"))


def _normalize_source(entry: dict[str, Any]) -> dict[str, Any]:
    """Normalize a source entry to the standard format.

    ``urls`` may mix plain strings with ``{url, title, group, country}``
    mappings; the mapping form gives a single stream its own display title,
    sidebar group and table country. The two are split on the way out: ``urls``
    becomes a flat string projection of every location, so consumers that treat
    it as a plain URL list cannot choke on a dict -- ``set()`` in
    :func:`_merge_iptv_urls`, handle parsing in
    :func:`load_streamers_from_sources`, and the emptiness check in
    ``WatchSmthnApp._load_source`` -- while ``entries`` preserves the original
    order and carries an :class:`EntryMeta` with the optional overrides.
    """
    name = entry.get("name", "unknown")
    source_type = entry.get("type", "tv")

    # Handle legacy "source" (string) -> "urls" (list)
    urls = entry.get("urls", [])
    if not urls:
        old_source = entry.get("source", "")
        if old_source:
            urls = [old_source]

    # Legacy: migrate "streamers" list into urls for "st" type sources
    if source_type == "st" and not urls:
        streamers = entry.get("streamers", [])
        for s in streamers:
            if isinstance(s, str):
                urls.append(s)
            elif isinstance(s, dict):
                urls.append(s.get("name", ""))

    categories = entry.get("categories", source_type == "tv")

    all_urls: list[str] = []
    entries: list[dict[str, Any]] = []
    for item in urls:
        if isinstance(item, dict):
            item_url = str(item.get("url", "")).strip()
            if not item_url:
                continue
            item_meta = _entry_meta(item)
        else:
            item_url = str(item).strip()
            item_meta = EntryMeta()
            if not item_url:
                continue
        all_urls.append(item_url)
        entries.append({"url": item_url, "meta": item_meta})

    return {
        "name": name,
        "type": source_type,
        "urls": all_urls,
        "entries": entries,
        "categories": bool(categories),
    }


def _merge_iptv_urls(defaults: list[dict[str, Any]], user_add: Any) -> list[dict[str, Any]]:
    """Merge add-iptv-urls into the iptv source."""
    if not user_add:
        return defaults

    override = False
    extra_urls: list[str] = []

    if isinstance(user_add, list):
        extra_urls = [str(u) for u in user_add]
    elif isinstance(user_add, dict):
        override = user_add.get("override", False)
        extra_urls = [str(u) for u in user_add.get("urls", [])]

    for source in defaults:
        if source["name"] == "iptv":
            if override:
                source["urls"] = extra_urls
            else:
                seen = set(source["urls"])
                for url in extra_urls:
                    if url not in seen:
                        source["urls"].append(url)
                        seen.add(url)
            break

    return defaults


def load_sources(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Load and merge sources from bundled defaults + user config.

    Returns a merged list of source dicts with standardized format.
    """
    # Load bundled defaults
    defaults: list[dict[str, Any]] = []
    if BUNDLED_CONFIG.exists():
        bundled = _load_config_file(BUNDLED_CONFIG)
        for entry in bundled.get("sources", []):
            defaults.append(_normalize_source(entry))

    # Apply add-iptv-urls from user config
    user_add_iptv = config.get("add-iptv-urls")
    if user_add_iptv:
        defaults = _merge_iptv_urls(defaults, user_add_iptv)

    # Load user sources
    user_sources = config.get("sources", [])
    seen_names: set[str] = {s["name"] for s in defaults}

    for entry in user_sources:
        source = _normalize_source(entry)
        name = source["name"]

        if name in RESERVED_SOURCE_NAMES:
            warnings.warn(
                f"Source name '{name}' is reserved. Skipping. "
                f"Use 'add-iptv-urls' to add URLs to the built-in iptv source.",
                UserWarning,
                stacklevel=2,
            )
            continue

        if name in seen_names:
            warnings.warn(
                f"Duplicate source name '{name}'. Skipping. "
                f"Please rename this source.",
                UserWarning,
                stacklevel=2,
            )
            continue

        seen_names.add(name)
        defaults.append(source)

    # Legacy: handle old "playlists" format
    if not defaults and config.get("playlists"):
        for entry in config["playlists"]:
            defaults.append(_normalize_source(entry))

    return defaults


PLATFORM_URLS: dict[str, str] = {
    "twitch": "https://www.twitch.tv/{name}",
    "youtube": "https://www.youtube.com/watch?v={name}",
    "bilibili": "https://www.bilibili.com/video/{name}",
    "dailymotion": "https://www.dailymotion.com/video/{name}",
    "afreecatv": "https://www.afreecatv.com/{name}",
}


def load_streamers_from_sources(sources: list[dict[str, Any]]) -> list[Channel]:
    """Load streamers from source entries."""
    channels: list[Channel] = []
    for source in sources:
        if source.get("type") != "st":
            continue
        platform = source["name"].lower()
        for username in source.get("urls", []):
            username = str(username).strip()
            if not username:
                continue
            url = PLATFORM_URLS.get(platform, "").format(name=username)
            if not url:
                url = username
            channels.append(Channel(
                name=username,
                url=url,
                group=platform.title(),
                content_type=ContentType.OTHER,
                extra={
                    "streamlink": True,
                    "platform": platform,
                    "username": username,
                },
            ))
    return channels


def _find_user_config() -> Path | None:
    """Find the user's config file."""
    for d in CONFIG_DIRS:
        for name in CONFIG_FILE_NAMES:
            p = d / name
            if p.exists():
                return p
    return None


def _load_or_create_user_config() -> tuple[Path, dict[str, Any]]:
    """Load or create the user config, returning (path, config_data)."""
    config_path = _find_user_config()
    if not config_path:
        config_dir = CONFIG_DIRS[0]
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "config.yaml"
        config_data: dict[str, Any] = {}
    else:
        config_data = _load_config_file(config_path)
    return config_path, config_data


def _write_config(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def save_handle_to_config(config: dict[str, Any], platform: str, handle: str) -> None:
    """Append a handle to a streamer source's urls list."""
    config_path, config_data = _load_or_create_user_config()
    sources = config_data.setdefault("sources", [])
    target = None
    for s in sources:
        if s.get("name") == platform:
            target = s
            break
    if target is None:
        target = {"name": platform, "type": "st", "urls": [], "categories": False}
        sources.append(target)
    urls = target.setdefault("urls", [])
    if handle not in urls:
        urls.append(handle)
    _write_config(config_path, config_data)


def save_custom_source_to_config(
    config: dict[str, Any], entry: dict[str, Any]
) -> None:
    """Save a custom TV source to the user config's sources section."""
    config_path, config_data = _load_or_create_user_config()
    sources = config_data.setdefault("sources", [])
    sources.append({
        "name": entry["name"],
        "type": "tv",
        "urls": entry.get("urls", []),
        "categories": True,
    })
    _write_config(config_path, config_data)
