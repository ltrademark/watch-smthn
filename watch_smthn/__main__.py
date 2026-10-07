"""Entry point for watch somethin."""

from __future__ import annotations

import argparse
import os
import sys

from .app import WatchSmthnApp
from .debug import dbg, setup_debug


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="watch-smthn",
        description="A terminal browser for stream playlists.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="trace config and launch decisions to a log file",
    )
    parser.add_argument(
        "--debug-log",
        metavar="PATH",
        default=None,
        help="where --debug writes (default ~/.config/watch-smthn/debug.log)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    if args.debug or os.environ.get("WATCH_SMTHN_DEBUG"):
        path = setup_debug(args.debug_log)
        dbg(f"debug log: {path}")
        dbg(f"platform={sys.platform} python={sys.version.split()[0]}")
        dbg(f"argv={sys.argv}")
    app = WatchSmthnApp()
    app.run()


if __name__ == "__main__":
    main()
