#!/usr/bin/env bash
# Install watch-smthn on Linux (including WSL) and report what is still missing.
#
# Idempotent: on a machine that already works it changes nothing and touches no
# config. It deliberately does not probe for players itself, because the app
# resolves executables through more than PATH (player_paths overrides, .exe
# names, /mnt/c roots). All discovery happens in `watch-smthn --doctor`, which
# runs the app's own code.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"

say() { printf '%s\n' "$*"; }
die() { printf 'install.sh: %s\n' "$*" >&2; exit 1; }

python=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        python=$candidate
        break
    fi
done
[ -n "$python" ] || die "python3 not found; install Python 3.10 or newer first"

if ! "$python" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
    die "$("$python" --version 2>&1) is too old; 3.10 or newer is required"
fi

if [ ! -d .venv ]; then
    say "creating .venv"
    "$python" -m venv .venv || die "could not create .venv; on Debian or Ubuntu run: sudo apt install python3-venv"
fi

say "installing watch-smthn and its dependencies"
./.venv/bin/python -m pip install --quiet -e . || die "pip install -e . failed"

set +e
report="$(./.venv/bin/python -m watch_smthn --doctor 2>&1)"
doctor_status=$?
set -e
printf '%s\n' "$report"

installer="install"
for pair in "apt-get:sudo apt install" "dnf:sudo dnf install" \
            "pacman:sudo pacman -S" "zypper:sudo zypper install"; do
    tool=${pair%%:*}
    if command -v "$tool" >/dev/null 2>&1; then
        installer=${pair#*:}
        break
    fi
done

say ""
if printf '%s\n' "$report" | grep -q '^missing player'; then
    say "Not ready yet. Install a player, then run this script again:"
    say "  media player: $installer mpv    (or vlc, or ffplay from ffmpeg)"
fi
if printf '%s\n' "$report" | grep -q '^warning .*opener'; then
    if [ -n "${WSL_DISTRO_NAME:-}" ] || grep -qi microsoft /proc/version 2>/dev/null; then
        say "  browser opener: $installer wslu    (gives you wslview)"
    else
        say "  browser opener: $installer xdg-utils"
    fi
fi
if printf '%s\n' "$report" | grep -q '^warning .*streamlink'; then
    say "  optional:       $installer streamlink    (only for custom streamlink sources)"
fi

if [ "$doctor_status" -eq 0 ]; then
    say "Ready. Run it with:  ./.venv/bin/watch-smthn"
fi

exit "$doctor_status"
