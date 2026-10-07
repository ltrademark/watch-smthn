"""Player launcher - opens content in external players as new instances."""

from __future__ import annotations

from dataclasses import replace
from typing import BinaryIO, Optional

from .debug import dbg
from .launchers import (SpawnedProcess, normalize_path, open_url,
                        resolve_executable, spawn)
from .models import Player, PlayerType


DEFAULT_PLAYERS: list[Player] = [
    Player(
        name="MPV",
        player_type=PlayerType.MPV,
        command=["mpv"],
        args=["--no-terminal", "--force-window=yes"],
        is_default=True,
    ),
    Player(
        name="VLC",
        player_type=PlayerType.VLC,
        command=["vlc"],
        args=["--play-and-exit"],
    ),
    Player(
        name="ffplay",
        player_type=PlayerType.FFPLAY,
        command=["ffplay"],
        args=["-nodisp", "-autoexit"],
    ),
    Player(
        name="Open in browser",
        player_type=PlayerType.WEB,
    ),
]


def find_available_players(players: list[Player] | None = None,
                           paths: dict[str, str] | None = None) -> list[Player]:
    if players is None:
        players = DEFAULT_PLAYERS
    configured = paths or {}
    if configured:
        dbg(f"player_paths override: {configured}")
    available = []
    for p in players:
        if p.command:
            key = p.command[0]
            override = configured.get(key) or configured.get(p.name)
            if override:
                resolved = normalize_path(override)
                source = f"override {override!r}"
            else:
                resolved = resolve_executable(normalize_path(key))
                source = f"discovery of {key!r}"
            if resolved:
                available.append(replace(p, command=[resolved, *p.command[1:]]))
            dbg(f"player {p.name}: {resolved or 'NOT FOUND'} ({source})")
        elif p.player_type == PlayerType.WEB:
            available.append(p)
    dbg(f"available players: {[p.name for p in available]}")
    return available


def launch_player(player: Player, url: str,
                  sink: Optional[BinaryIO] = None,
                  detach: bool = False,
                  log_file: Optional[str] = None) -> Optional[SpawnedProcess]:
    if player.player_type == PlayerType.WEB:
        dbg(f"open in browser: {url}")
        return open_url(url, sink)
    cmd = player.build_command(url)
    if not cmd:
        dbg(f"launch {player.name}: empty command, refusing")
        return None
    if log_file:
        if player.player_type == PlayerType.MPV:
            cmd = [*cmd, f"--log-file={log_file}"]
            dbg(f"player log for {player.name}: {log_file}")
        else:
            dbg(f"player log ignored, {player.name} has no --log-file")
    dbg(f"launch {player.name}: {cmd}")
    return spawn(cmd, stderr=sink, detach=detach)
