# 👁️ Watch Something

A TUI for browsing and watching services online, like IPTV, twitch, youtube, and more.

## Requirements

- Python 3.10 or newer.
- A terminal with Unicode box-drawing characters and 256 color support.
- At least one of mpv, VLC, or ffplay. On Windows the standard install locations are searched too, so the player does not have to be on `PATH`. Only the players found show up in the picker.
- `streamlink`, required only for sources with `type: st`.
- Nothing else. Launching is platform dispatched, so a native Windows shell, WSL and Linux all work.

## Disclaimer

This project uses the IPTV source lists from https://github.com/iptv-org/iptv. Through parameters below, this list can be augmented or ignored altogether.

## Install

Linux and WSL, one line (no git needed):

```bash
curl -fsSL https://raw.githubusercontent.com/ltrademark/watch-smthn/master/watch-smthn.sh | bash
```

Windows, from PowerShell, one line (no git needed):

```powershell
irm https://raw.githubusercontent.com/ltrademark/watch-smthn/master/watch-smthn.ps1 | iex
```

Each one-liner downloads the source archive from GitHub into `~/.local/share/watch-smthn` (Windows: `%LOCALAPPDATA%\watch-smthn`) and runs the same installer a checkout gives you, so both routes end in the same place; the tree is identical, only its root differs, which is how the by-hand paths below work with the location swapped. Re-run the one-liner to update. It executes code from this repository without asking; download the script and read it first if you would rather not pipe it.

With git, which is what you want if you plan to contribute:

Linux and WSL:

```bash
git clone https://github.com/ltrademark/watch-smthn watch-smthn
cd watch-smthn
./install.sh
```

Windows, from PowerShell:

```powershell
git clone https://github.com/ltrademark/watch-smthn
cd watch-smthn
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Each script creates its own venv (`.venv` for Linux and WSL, `.venv-win` for Windows), installs the two Python dependencies (`textual` and `pyyaml`, pulled in automatically from `pyproject.toml`), puts `watch-smthn` on `PATH`, and then prints a dependency report so a missing tool shows up here instead of as a silent failure later. Both are idempotent: running one again on a working install changes nothing, and neither touches your config. A script exits 1 when the report still finds no player and 2 when the script itself could not run, which is what CI keys off.

On Linux and WSL the command is linked into `~/.local/bin`; on Windows `.venv-win\Scripts` is appended to your user `PATH`. If the report still says it is not on `PATH`, add the line it prints to your shell profile and open a new terminal.

**One clone, both tabs.** Because the two platforms keep separate venvs, an Ubuntu tab and a PowerShell tab of the same clone in one Windows Terminal window can both run `watch-smthn` without touching each other: each installer only ever manages its own directory. If the clone was installed before that split, run each script once to migrate. `.\install.ps1` moves your `PATH` entry from `.venv\Scripts` to `.venv-win\Scripts` and says so, while `./install.sh` reclaims `.venv` when it finds a Windows build in it and says so too.

To do it by hand instead:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

**Which terminal.** Tested in Windows Terminal (PowerShell and WSL tabs) and plain Linux terminals. Classic conhost, the legacy Windows console, is unsupported: its raster font mangles the TUI's box drawing and emoji. Use Windows Terminal.

### Checking an installation

```bash
watch-smthn --doctor
```

One fact per line: where the config and favorites files are, which command `watch-smthn` resolves to and whether this shell can reach it, what each player resolved to, which editor `ctrl+e` will use, the URL opener, and whether `streamlink` is present. It creates no files, launches nothing, and exits non-zero only when no player at all was found, which is what the install scripts key their hints off. The output is safe to paste into a bug report.

By hand, without the command on `PATH`: `.venv/bin/watch-smthn --doctor`.

## Run

```bash
watch-smthn
```

That is the install scripts' work. Without them, or before opening a new shell:

```bash
.venv/bin/watch-smthn
# or
.venv/bin/python -m watch_smthn
```

On Windows, by hand: `.\.venv-win\Scripts\watch-smthn.exe`.

### Debugging

```bash
watch-smthn --debug
# or .venv/bin/watch-smthn --debug
```

Traces the decisions behind a launch to `~/.config/watch-smthn/debug.log`: which config file was read, which `player_paths` override matched, the exact command built for a channel, the pid `spawn` got back, and the full traceback when it raises. Use `--debug-log PATH` to write somewhere else, or set `WATCH_SMTHN_DEBUG=1` to turn it on without changing how you launch the app.

Nothing is logged unless you ask for it, and the file sits outside the repository so the TUI keeps the terminal to itself.

mpv runs with `--no-terminal`, so its own messages reach neither the terminal nor the handle the app captures. Under `--debug` it is handed a log file of its own instead, which is what the failure toast reads from once the settle window closes; that file is removed after the one read.

### When a launch fails

Before a URL reaches a player it is checked structurally: an empty row, a missing `http://` scheme, or an unsupported scheme is refused with a toast naming the reason rather than being handed on to fail in silence.

After that the app does not second-guess the stream. A couple of seconds after launching, if the player exited with a failure the toast shows the useful lines from its own output, such as the ffmpeg error behind a dead source. A player still running is left alone. Nothing is ever blocked on a pre-flight network check, because plenty of live sources reject a plain probe while opening normally in a real player.

## Keybinds

| Key           | Action                |
| ------------- | --------------------- |
| `q`, `ctrl+c` | Quit                  |
| `esc`         | Clear search          |
| `/`           | Focus search          |
| `enter`       | Play the selected row |
| `p`           | Pick a player         |
| `f`           | Toggle favorite       |
| `ctrl+e`      | Open the config file  |
| `ctrl+r`      | Reload config         |
| `left`        | Focus Categories      |
| `right`       | Focus Channels        |

## Configuration

### Where it lives

The app loads the first file it finds, checking directories in this order and filenames within each directory:

- `~/.config/watch-smthn/config.yaml`
- `~/.config/watch-smthn/config.yml`
- `~/.config/watch-smthn/config.json`
- `~/.watch-smthn/config.yaml`
- `~/.watch-smthn/config.yml`
- `~/.watch-smthn/config.json`

The extension picks the parser: `.yaml` and `.yml` go through `yaml.safe_load`, `.json` through `json.loads`. If nothing matches, the bundled `watch_smthn/data/default_config.yaml` is used, which ships a single built-in `iptv` source.

Favorites are stored separately at `~/.config/watch-smthn/favorites.json`. The app writes that file itself, so edit the YAML and leave the JSON alone.

### Top-level keys

| Key             | Purpose                                                     |
| --------------- | ----------------------------------------------------------- |
| `sources`       | Everything that appears in the Sources panel.               |
| `players`       | Extra players beyond the four built-ins.                    |
| `player_paths`  | Absolute paths for players that discovery misses.           |
| `editor`        | The editor `ctrl+e` opens the config in.                    |
| `add-iptv-urls` | Extra playlist URLs merged into the built-in `iptv` source. |

Anything else in the file is ignored.

### sources example:

```yaml
sources:
  - name: Other TV
    type: tv
    categories: true
    urls:
      - https://example.com/playlist_usa.m3u8
      - url: https://example.com/VIDEO_1.m3u8
        title: Some Channel
        group: News
        country: US
  - name: Twitch
    type: st
    categories: false
    urls:
      - Twitch
      - NASA
```

| Key          | Type         | Default                           | Notes                                                                                        |
| ------------ | ------------ | --------------------------------- | -------------------------------------------------------------------------------------------- |
| `name`       | str          | required                          | Sidebar label. `iptv` is reserved; a second source with that name is skipped with a warning. |
| `type`       | `tv` or `st` | `tv`                              | `tv` reads playlists and direct streams, `st` holds streamlink handles.                      |
| `urls`       | list         | `[]`                              | Plain strings, or mappings as described below.                                               |
| `categories` | bool         | `true` for `tv`, `false` for `st` | `false` hides the Categories panel while this source is selected.                            |
| `source`     | str          | legacy                            | Old single-URL form, folded into `urls` on load.                                             |
| `streamers`  | list         | legacy                            | Old handle list for `st` sources, folded into `urls` on load.                                |

### URL sub-entries

An entry in `urls` is either a plain string, meaning "load this and use whatever the file says", or a mapping that lets you name the result yourself.

| Key | One row (an HLS playlist, or a URL that failed to load) | Many rows (a channel list) |
| --- | --- | --- |
| `url` | Required. The location to load. | Same. |
| `title` | Becomes the row's Name. | Becomes the row's Group, but only when `group` is absent. |
| `group` | Becomes the row's Group, overriding the default. | Becomes the Group for every row, replacing the file's own `group-title`. |
| `country` | Becomes the row's Country. | Becomes the Country for every row, replacing the file's own `tvg-country`. |

Some details worth knowing:

- On a single row, the default Group is the source name, unless that would duplicate the row's own Name, in which case it is left blank.
- Overrides are applied unconditionally so nothing you typed is dropped, including over values the file already supplied.
- If a mapping turns out to point at a channel list, `title` has nothing left to do once `group` is set, and is ignored.
- If the fetch fails or returns no rows, the row falls back to the title if there is one, otherwise to the URL filename with separators turned into spaces. Its Group becomes the source name unless that would duplicate the Name.
- `country` is stored exactly as you write it, and the `country:` search parameter matches exactly, so use codes like `US` or `PH` rather than country names.

### Set up another player

```yaml
players:
  - name: Custom Player
    type: custom
    command: [myplayer]
    args: ["--fullscreen"]
    default: true
```

| Key            | Type                                                                    | Default  | Notes                                                                                                 |
| -------------- | ----------------------------------------------------------------------- | -------- | ----------------------------------------------------------------------------------------------------- |
| `name`         | str                                                                     | `Custom` | Shown in the player picker.                                                                           |
| `type`         | one of `mpv`, `vlc`, `ffplay`, `iptv`, `sling`, `plex`, `web`, `custom` | `custom` | Chooses how the command is built.                                                                     |
| `command`      | list of str                                                             | `[]`     | Executable plus any fixed leading arguments. Empty means the `type` itself is used as the executable. |
| `args`         | list of str                                                             | `[]`     | Extra arguments inserted before the URL.                                                              |
| `url_template` | str                                                                     | unset    | Read from the file and stored, but never used when building a command.                                |
| `default`      | bool                                                                    | `false`  | Marks this as the preferred player.                                                                   |

Four players are built in: MPV (default), VLC, ffplay, and Open in browser. The browser player shells out to `xdg-open`. A player only appears in the picker if its command is found on `PATH`, which is why an empty `command` list plus a `custom` type never shows up.

### player_paths

Points a player at an executable that auto-discovery never finds. Keys are the built-in player keys (`mpv`, `vlc`, `ffplay`), the player's `name`, or `streamlink` for the streamlink helper, values are the path.

```yaml
player_paths:
  mpv: C:\ProgramData\chocolatey\lib\mpv.install\tools\mpv.exe
  VLC: /mnt/c/Program Files/VideoLAN/VLC/vlc.exe
  streamlink: D:\tools\streamlink\streamlink.exe
```

An override is used exactly as written, without an existence check, so a wrong path shows up as a failed launch naming the path instead of silently dropping the player. Under WSL a `C:\...` or `C:/...` value is rewritten to `/mnt/c/...` first, so the same line works on Windows and on Linux. The default Windows install of streamlink (`C:\Program Files\Streamlink\bin`, or `/mnt/c/Program Files/Streamlink/bin` under WSL) is found on its own, so `streamlink:` is only needed for a custom location.

### editor

```yaml
editor: code
```

`ctrl+e` splits this value the way a shell would, so `editor: "code --wait"` and `editor: "kitty -e vim"` both work. It is checked before `VISUAL` and `EDITOR`, which are only consulted when `editor` is unset. The first word may be an absolute path (`editor: /usr/bin/nano`), and everything after it is passed to that command as arguments.

On Windows, with `editor` unset, the `.yaml` file association is used first. When there is no usable association, the editor is looked for in the known install locations in the order `code`, `notepad++`, `notepad`, and a machine with none of them reports all three by name instead of silently opening nothing. Under WSL the same Windows executables are found through `/mnt/c/...`.

### add-iptv-urls

Adds playlist URLs to the built-in `iptv` source without redefining it.

```yaml
# Append, skipping anything already listed
add-iptv-urls:
  - https://example.com/playlist.m3u8

# Or replace the built-in list entirely
add-iptv-urls:
  override: true
  urls:
    - https://example.com/playlist.m3u8
```

A plain list appends and deduplicates. The mapping form takes `override` and `urls`, and only `override: true` clears the existing entries. This key has no effect on any other source.

### Reserved names and gotchas

- `iptv` is reserved. It always exists as a bundled source, so a user source with that name is dropped with a warning.
- `type: st` sources ignore the player picker. They always launch through `streamlink <url> best`, so `streamlink` must be installed for those rows to play.
- The platform for an `st` source is the source name lowercased, matched against Twitch, YouTube, Bilibili, Dailymotion, and AfreecaTV. An unmatched name still works; the handle is passed to streamlink as-is.
- Search parameters are `country:`, `lang:`, and `group:`. Plain text matches name, group, content type, country, and language.

### Editing

`ctrl+e` opens the config file in your default editor, creating `~/.config/watch-smthn/config.yaml` from the bundled default if it does not exist yet. `ctrl+r` reloads the config without restarting the application. The editor is picked from `editor` in the config, then, on Windows, the file association for the file and then the known install locations of `code`, `notepad++` and `notepad`; elsewhere `VISUAL`, then `EDITOR`, then `nano`.

## Tests

```bash
.venv/bin/python tests/regression.py
```

The suite is a single script using `asyncio` and Textual's own headless `run_test`, so no test framework needs installing. It prints a pass count and exits nonzero on any failure.

## Project layout

- `watch_smthn/app.py`: Textual app with layout, CSS, sidebar, table, search, and the loading pipeline.
- `watch_smthn/config.py`: config discovery, source normalization, and writing new sources back out.
- `watch_smthn/m3u_parser.py`: M3U parsing, HLS playlist collapsing, and per-entry overrides.
- `watch_smthn/models.py`: `Channel`, `Playlist`, `Player`, and `EntryMeta`.
- `watch_smthn/players.py`: player discovery and launching.
- `watch_smthn/streamers.py`: streamlink command construction.
- `watch_smthn/favorites.py`: favorites persistence.
- `tests/regression.py`: the regression suite.

## License

[CC BY-NC-SA 4.0](LICENSE), copyright Ltrademark.

You are free to share and remix this code, with attribution to Ltrademark, under three conditions: no commercial use, derivatives keep the same license, and you indicate whether you changed anything. No resale, no profit.

Creative Commons is not a lawyer and this is not legal advice. The full terms are in [LICENSE](LICENSE).
