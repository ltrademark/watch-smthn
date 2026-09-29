"""Player launcher - opens content in external players as new instances."""

from __future__ import annotations

import shutil
import subprocess
from typing import Optional

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


def find_available_players(players: list[Player] | None = None) -> list[Player]:
    if players is None:
        players = DEFAULT_PLAYERS
    available = []
    for p in players:
        if p.command:
            if shutil.which(p.command[0]):
                available.append(p)
        elif p.player_type == PlayerType.WEB:
            available.append(p)
    return available


def launch_player(player: Player, url: str) -> Optional[subprocess.Popen]:
    cmd = player.build_command(url)
    if not cmd:
        return None
    try:
        shell_cmd = f"nohup {' '.join(cmd)} >/dev/null 2>&1 &"
        proc = subprocess.Popen(
            shell_cmd,
            shell=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return proc
    except FileNotFoundError:
        return None
    except Exception:
        return None
