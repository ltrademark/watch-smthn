"""Streamlink-based streamer integration (Twitch, YouTube, Bilibili, etc.)."""

from __future__ import annotations


def build_streamlink_command(url: str, quality: str = "best",
                             executable: str = "streamlink") -> list[str]:
    return [executable, url, quality]
