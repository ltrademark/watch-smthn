"""Favorites persistence for watch somethin."""

from __future__ import annotations

import json
from pathlib import Path

FAVORITES_FILE = Path.home() / ".config" / "watch-smthn" / "favorites.json"


def _ensure_dir() -> None:
    FAVORITES_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_favorites() -> set[str]:
    if not FAVORITES_FILE.exists():
        return set()
    try:
        data = json.loads(FAVORITES_FILE.read_text(encoding="utf-8"))
        return set(data) if isinstance(data, list) else set()
    except (json.JSONDecodeError, OSError):
        return set()


def save_favorites(favorites: set[str]) -> None:
    _ensure_dir()
    FAVORITES_FILE.write_text(
        json.dumps(sorted(favorites), indent=2),
        encoding="utf-8",
    )


def toggle_favorite(favorites: set[str], url: str) -> bool:
    if url in favorites:
        favorites.remove(url)
        save_favorites(favorites)
        return False
    favorites.add(url)
    save_favorites(favorites)
    return True
