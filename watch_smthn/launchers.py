"""Platform-dispatched launching of external processes and URLs.

``sys.platform`` is read inside each function rather than at import time so that the
``win32`` branch stays reachable from tests on Linux by patching ``sys.platform``
around the call.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import BinaryIO, Optional
from urllib.parse import urlparse

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


_LAUNCHABLE_SCHEMES = frozenset({"http", "https", "rtmp", "rtmps", "rtsp", "file"})


def check_launchable(url: Optional[str]) -> Optional[str]:
    """Return why a URL cannot be handed to a player, or None when it can.

    Deliberately structural only. Whether the stream actually plays is decided
    by the player itself, because an HTTP probe would reject plenty of live
    sources that a real client opens without trouble.
    """
    text = (url or "").strip()
    if not text:
        return "this channel has no URL"
    parsed = urlparse(text)
    if not parsed.scheme:
        return "the URL is missing its http:// scheme"
    if parsed.scheme.lower() not in _LAUNCHABLE_SCHEMES:
        return f"unsupported scheme {parsed.scheme!r}"
    if parsed.scheme.lower() != "file" and not parsed.netloc:
        return "the URL has no host"
    return None


def open_sink() -> BinaryIO:
    """A stderr target that outlives the call and can be read back later."""
    return tempfile.TemporaryFile(mode="w+b")


def read_tail(sink: BinaryIO, limit: int = 800) -> str:
    try:
        sink.flush()
        sink.seek(0, os.SEEK_END)
        size = sink.tell()
        sink.seek(max(0, size - limit))
        data = sink.read()
    except (OSError, ValueError):
        return ""
    return data.decode("utf-8", "replace")


_SUMMARY_HINT = re.compile(
    r"error|fail|invalid|denied|refused|no such|unable|not found|unsupported|denied",
    re.I,
)


def summarize(text: str, line_width: int = 160) -> str:
    """Collapse raw player output to the couple of lines worth showing."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""
    interesting = [ln for ln in lines if _SUMMARY_HINT.search(ln)]
    chosen = interesting[-2:] or lines[-2:]
    return " | ".join(ln[:line_width] for ln in chosen)


def spawn(argv: list[str], *, stderr: Optional[BinaryIO] = None) -> Optional[subprocess.Popen]:
    if not argv:
        dbg("spawn: empty argv, nothing to run")
        return None
    sink = subprocess.DEVNULL if stderr is None else stderr
    dbg(f"spawn: {argv}")
    try:
        if _is_windows():
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=sink,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            proc = subprocess.Popen(
                argv,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=sink,
                start_new_session=True,
            )
    except BaseException as exc:
        dbg_error("spawn raised", exc)
        raise
    dbg(f"spawn: ok, pid={getattr(proc, 'pid', '?')}")
    return proc


def open_url(url: str, sink: Optional[BinaryIO] = None) -> Optional[subprocess.Popen]:
    if _is_windows():
        os.startfile(url)
        return None
    return spawn(["xdg-open", url], stderr=sink)


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
