#!/usr/bin/env bash
# One-line installer for watch-smthn, no git required.
#
#   curl -fsSL https://raw.githubusercontent.com/ltrademark/watch-smthn/master/watch-smthn.sh | bash
#
# Downloads the source archive from GitHub into a fixed directory and runs the
# project's own install.sh inside it, so the one-liner and a git checkout end
# in the same place. Re-running it refreshes the source and reinstalls.
#
# Overrides, mostly for testing:
#   WATCH_SMTHN_HOME         install directory (default: ~/.local/share/watch-smthn)
#   WATCH_SMTHN_ARCHIVE_URL  source archive, .tar.gz with a single top directory
set -euo pipefail

repo="ltrademark/watch-smthn"
target="${WATCH_SMTHN_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/watch-smthn}"
target="${target%/}"
archive="${WATCH_SMTHN_ARCHIVE_URL:-https://github.com/$repo/archive/refs/heads/master.tar.gz}"

say() { printf '%s\n' "$*"; }
die() { printf 'watch-smthn.sh: %s\n' "$*" >&2; exit 2; }

command -v tar >/dev/null 2>&1 || die "tar not found; install it first"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$archive" -o "$tmp/source.tar.gz"
elif command -v wget >/dev/null 2>&1; then
    wget -qO "$tmp/source.tar.gz" "$archive"
else
    die "need curl or wget to download the source"
fi

mkdir "$tmp/unpacked"
tar -xzf "$tmp/source.tar.gz" -C "$tmp/unpacked"

src=""
for dir in "$tmp/unpacked"/*/; do
    src="${dir%/}"
    break
done
[ -n "$src" ] && [ -f "$src/install.sh" ] || die "the download did not contain install.sh"

if [ -e "$target/.git" ]; then
    say "found a git checkout at $target; leaving its source alone"
    say "  refresh it with: git -C \"$target\" pull"
elif [ -e "$target" ]; then
    say "refreshing $target"
    rm -rf "$target"
    mkdir -p "$(dirname "$target")"
    mv "$src" "$target"
else
    mkdir -p "$(dirname "$target")"
    mv "$src" "$target"
    say "downloaded to $target"
fi

# The outer bash may still be reading this script from the pipe, so the
# installer gets /dev/null for stdin instead of stealing the rest of it.
# install.sh never prompts anyway.
bash "$target/install.sh" </dev/null
