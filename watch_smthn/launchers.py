"""Platform-dispatched launching of external processes and URLs.

``sys.platform`` is read inside each function rather than at import time so that the
``win32`` branch stays reachable from tests on Linux by patching ``sys.platform``
around the call.
"""

from __future__ import annotations

import errno
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


def _running(pid: int) -> bool:
    """True while pid exists and is more than a corpse awaiting its reaper.

    A detached player is reaped by init rather than by us, so for a moment
    after it dies it is still a zombie and kill(pid, 0) keeps succeeding.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return True  # no /proc: existence is all we can go on
    return stat[stat.rindex(")") + 1:].split()[0] != "Z"


class DetachedProcess:
    """A player started outside this process's own tree.

    A tiling compositor places a new window against the window owned by the
    process that opened it, so a player spawned while this app owns the
    focused window is handed that window's whole cell instead of a split of
    its own.  Starting the player through a shell that exits immediately
    reparents it to init and the tiling comes out right.  The price is that
    it is no longer our child, so poll() can only say alive or gone and never
    an exit status, which is all the settle window needs.
    """

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self._code: Optional[int] = None

    def poll(self) -> Optional[int]:
        """None while the player runs, -1 once it is gone (status unknown)."""
        if self._code is None and not _running(self.pid):
            self._code = -1
        return self._code


SpawnedProcess = subprocess.Popen | DetachedProcess


def _detach_script(argv: list[str]) -> str:
    """A shell line that runs argv in the background and prints its pid.

    The background job inherits stderr, which is our sink, while stdout is
    kept for the pid so the shell can exit straight away and leave the player
    with no ancestor of ours before its window maps.
    """
    return f"{shlex.join(argv)} 1>&2 & echo $!"


def _spawn_detached(argv: list[str], sink: BinaryIO) -> DetachedProcess:
    program = argv[0]
    if not shutil.which(program):
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), program)
    shell = subprocess.Popen(
        ["/bin/sh", "-c", _detach_script(argv)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=sink,
        shell=False,
        start_new_session=True,
        text=True,
    )
    if shell.stdout is None:
        shell.wait()
        raise OSError(f"detached launch of {program} has no way to report a pid")
    with shell.stdout:
        reported = shell.stdout.readline().strip()
    shell.wait()
    if not reported.isdigit():
        raise OSError(f"detached launch of {program} reported no pid")
    dbg(f"spawn: detached pid={reported} for {program}")
    return DetachedProcess(int(reported))


def spawn(argv: list[str], *, stderr: Optional[BinaryIO] = None,
          detach: bool = False) -> Optional[SpawnedProcess]:
    """Start argv, optionally outside this process's own tree.

    detach is what makes a launched player tile normally; see DetachedProcess.
    """
    if not argv:
        dbg("spawn: empty argv, nothing to run")
        return None
    sink = subprocess.DEVNULL if stderr is None else stderr
    dbg(f"spawn: {argv}")
    try:
        if _is_windows() or not detach:
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
        else:
            proc = _spawn_detached(argv, sink)
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
