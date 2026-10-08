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
# Exit codes are part of the contract: 1 means the install ran and the report
# still found no player, 2 means this script itself could not do its job.
# CI allows 1 on a bare runner and fails on anything above it.
die() { printf 'install.sh: %s\n' "$*" >&2; exit 2; }

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

# Put the command where this shell and future ones can find it, unless it is
# already reachable some other way (an entry for .venv/bin on PATH does the
# same job and is left alone).  The link is recreated when it dangles, so
# moving the repository does not strand an old copy.
ours="$here/.venv/bin/watch-smthn"
link="$HOME/.local/bin/watch-smthn"
if [ "$(command -v watch-smthn || true)" != "$ours" ]; then
    if [ -L "$link" ] && [ "$(readlink "$link")" = "$ours" ]; then
        :
    else
        mkdir -p "$HOME/.local/bin" || die "could not create $HOME/.local/bin"
        if [ -e "$link" ] || [ -L "$link" ]; then
            rm -f "$link" || die "could not replace $link"
        fi
        ln -sfn "$ours" "$link" || die "could not link $link to $ours"
        say "linked $link -> $ours"
    fi
fi

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
if printf '%s\n' "$report" | grep -q '^warning .*launcher'; then
    case "${SHELL:-}" in
        */fish) say "  PATH:            fish_add_path ~/.local/bin    then open a new shell" ;;
        *)      say '  PATH:            export PATH="$HOME/.local/bin:$PATH"    then open a new shell' ;;
    esac
    say "                   until then, run $link"
fi

if [ "$doctor_status" -eq 0 ]; then
    if [ "$(command -v watch-smthn || true)" = "$ours" ]; then
        say "Ready. Run it with:  watch-smthn"
    else
        say "Ready. Run it with:  $link"
    fi
fi

exit "$doctor_status"
