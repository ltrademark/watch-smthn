"""Optional tracing for launch and config problems.

Enabled with ``--debug`` (or ``WATCH_SMTHN_DEBUG=1``). Output goes to a file
outside the repository, because the TUI owns the terminal and would swallow
anything printed to stdout. Every call is a no-op until :func:`setup_debug`
runs, so the calls cost nothing in normal use.
"""

from __future__ import annotations

import logging
import os
import traceback
from pathlib import Path

LOGGER = logging.getLogger("watch_smthn")
_enabled = False


def default_log_path() -> Path:
    override = os.environ.get("WATCH_SMTHN_DEBUG_LOG")
    if override:
        return Path(override)
    return Path.home() / ".config" / "watch-smthn" / "debug.log"


def setup_debug(log_path: str | Path | None = None) -> Path:
    global _enabled
    target = Path(log_path) if log_path else default_log_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    for handler in list(LOGGER.handlers):
        LOGGER.removeHandler(handler)
        handler.close()
    handler = logging.FileHandler(target, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.DEBUG)
    _enabled = True
    return target


def disable_debug() -> None:
    global _enabled
    for handler in list(LOGGER.handlers):
        LOGGER.removeHandler(handler)
        handler.close()
    _enabled = False


def is_enabled() -> bool:
    return _enabled


def dbg(message: str) -> None:
    if _enabled:
        LOGGER.debug(message)


def dbg_error(message: str, exc: BaseException) -> None:
    if not _enabled:
        return
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip()
    LOGGER.debug("%s\n%s", message, detail)
