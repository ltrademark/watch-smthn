"""Platform-dispatched launching of external processes and URLs.

``sys.platform`` is read inside each function rather than at import time so that the
``win32`` branch stays reachable from tests on Linux by patching ``sys.platform``
around the call.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional


def _is_windows() -> bool:
    return sys.platform == "win32"


def spawn(argv: list[str]) -> Optional[subprocess.Popen]:
    if not argv:
        return None
    if _is_windows():
        return subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return subprocess.Popen(
        argv,
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def open_url(url: str) -> Optional[subprocess.Popen]:
    if _is_windows():
        os.startfile(url)
        return None
    return spawn(["xdg-open", url])


def open_in_editor(path: Path) -> Optional[subprocess.Popen]:
    if _is_windows():
        os.startfile(str(path))
        return None
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano"
    argv = shlex.split(editor) or ["nano"]
    term = os.environ.get("TERM_PROGRAM")
    if not term or not shutil.which(term):
        term = None
        for candidate in ("kitty", "alacritty", "ghostty", "wezterm", "foot", "xterm"):
            if shutil.which(candidate):
                term = candidate
                break
    if term == "kitty":
        return spawn([term, *argv, str(path)])
    if term:
        return spawn([term, "-e", *argv, str(path)])
    return spawn([*argv, str(path)])
