"""Entry point for watch somethin."""

from __future__ import annotations

import sys

from .app import WatchSmthnApp


def main() -> None:
    app = WatchSmthnApp()
    app.run()


if __name__ == "__main__":
    main()
