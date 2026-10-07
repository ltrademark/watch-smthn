"""Report what this installation can actually find.

Backs ``watch-smthn --doctor``, which the install scripts call instead of
reimplementing executable discovery in shell.  It only reads: no config file
or favorites file is created, nothing is launched, and every line of output is
a stable ``key value`` pair so a bug report or a script can grep it.
"""

from __future__ import annotations

import os
import shlex
import sys
from importlib import metadata
from pathlib import Path

from .config import (CONFIG_DIRS, _find_config, get_custom_players,
                     get_editor, get_player_paths, load_config)
from .favorites import FAVORITES_FILE
from .launchers import EDITOR_CANDIDATES, OPENERS, resolve_executable
from .models import PlayerType
from .players import DEFAULT_PLAYERS, find_available_players

def _version() -> str:
    try:
        return metadata.version("watch-smthn")
    except metadata.PackageNotFoundError:
        return "unknown"


def _config_path() -> tuple[Path, bool]:
    found = _find_config()
    if found:
        return found, True
    return CONFIG_DIRS[0] / "config.yaml", False


def _describe_editor(config: dict) -> str:
    configured = get_editor(config)
    if configured:
        head = shlex.split(configured)[0]
        return f"{resolve_executable(head) or 'missing'} (from config)"
    if sys.platform == "win32":
        for candidate in EDITOR_CANDIDATES:
            resolved = resolve_executable(candidate)
            if resolved:
                return f"{resolved} (association, then {', '.join(EDITOR_CANDIDATES)})"
        return f"missing (association, then {', '.join(EDITOR_CANDIDATES)})"
    default = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano"
    head = (shlex.split(default) or ["nano"])[0]
    return f"{resolve_executable(head) or 'missing'} ({default})"


def run_doctor() -> int:
    """Print the report and return 0 when this install can actually run."""
    config = load_config()
    lines = ["watch-smthn doctor",
             f"version {_version()}",
             f"python {sys.version.split()[0]} ({sys.platform})"]

    cfg, present = _config_path()
    lines.append(f"config {cfg} {'present' if present else 'missing'}")
    lines.append(f"favorites {FAVORITES_FILE} "
                 f"{'present' if FAVORITES_FILE.exists() else 'missing'}")

    players = DEFAULT_PLAYERS + get_custom_players(config)
    available = find_available_players(players, get_player_paths(config))
    local = 0
    for player in players:
        if player.player_type is PlayerType.WEB:
            lines.append(f"player {player.name} built in")
            continue
        found = next((p for p in available if p.name == player.name), None)
        if found and found.command:
            lines.append(f"player {player.name} {found.command[0]}")
            local += 1
        else:
            lines.append(f"player {player.name} missing")

    lines.append(f"editor {_describe_editor(config)}")

    opener = next((name for name in OPENERS if resolve_executable(name)), None)
    lines.append(f"opener {resolve_executable(opener) if opener else 'missing'}")
    stream = resolve_executable("streamlink")
    lines.append(f"streamlink {stream or 'missing'}")

    # Only a missing player stops the app from playing anything at all, so it
    # alone decides the exit code.  The rest are reported for the install
    # scripts to hint about without failing a working installation.
    gaps = []
    warnings = []
    if not local:
        gaps.append("player")
    if not opener:
        warnings.append("opener")
    if not stream:
        warnings.append("streamlink")
    if gaps:
        lines.append(f"missing {', '.join(gaps)}")
    if warnings:
        lines.append(f"warning {', '.join(warnings)} missing")
    lines.append("status ok" if not gaps else "status not ok")

    print("\n".join(lines))
    return 0 if not gaps else 1
