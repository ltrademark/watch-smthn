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

from .debug import dbg, dbg_error


def _is_windows() -> bool:
    return sys.platform == "win32"


_KNOWN_INSTALL_PATHS: dict[str, tuple[str, ...]] = {
    "vlc": ("VideoLAN/VLC/vlc.exe", "Programs/VideoLAN/VLC/vlc.exe"),
    "mpv": ("mpv/mpv.exe", "Programs/mpv/mpv.exe"),
}


def _known_install_roots() -> list[Path]:
    roots: list[Path] = []
    for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        value = os.environ.get(var)
        if value:
            roots.append(Path(value))
    roots.append(Path("/mnt/c/Program Files"))
    roots.append(Path("/mnt/c/Program Files (x86)"))
    return roots


def resolve_executable(name: str) -> Optional[str]:
    found = shutil.which(f"{name}.exe") or shutil.which(name)
    if found:
        return found
    for relative in _KNOWN_INSTALL_PATHS.get(name, ()):
        for root in _known_install_roots():
            candidate = root / relative
            if candidate.is_file():
                return str(candidate)
    return None


def normalize_path(value: str) -> str:
    if _is_windows() or len(value) < 3:
        return value
    if value[1] != ":" or not value[0].isalpha() or value[2] not in "\\/":
        return value
    tail = value[2:].replace("\\", "/").lstrip("/")
    return f"/mnt/{value[0].lower()}/{tail}"


def spawn(argv: list[str]) -> Optional[subprocess.Popen]:
    if not argv:
        dbg("spawn: empty argv, nothing to run")
        return None
    dbg(f"spawn: {argv}")
    try:
        if _is_windows():
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            proc = subprocess.Popen(
                argv,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
    except BaseException as exc:
        dbg_error("spawn raised", exc)
        raise
    dbg(f"spawn: ok, pid={getattr(proc, 'pid', '?')}")
    return proc


def open_url(url: str) -> Optional[subprocess.Popen]:
    if _is_windows():
        os.startfile(url)
        return None
    return spawn(["xdg-open", url])


def open_in_editor(path: Path, editor: Optional[str] = None) -> Optional[subprocess.Popen]:
    explicit = shlex.split(editor) if editor else []
    if explicit:
        dbg(f"editor: configured {explicit!r} for {path}")
        return spawn([*explicit, str(path)])
    if _is_windows():
        dbg(f"editor: os.startfile({path})")
        os.startfile(str(path))
        return None
    fallback = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano"
    argv = shlex.split(fallback) or ["nano"]
    term = os.environ.get("TERM_PROGRAM")
    if not term or not shutil.which(term):
        term = None
        for candidate in ("kitty", "alacritty", "ghostty", "wezterm", "foot", "xterm"):
            if shutil.which(candidate):
                term = candidate
                break
    dbg(f"editor: fallback editor={argv!r} term={term!r}")
    if term == "kitty":
        return spawn([term, *argv, str(path)])
    if term:
        return spawn([term, "-e", *argv, str(path)])
    return spawn([*argv, str(path)])
