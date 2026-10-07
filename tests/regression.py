import asyncio, copy, os, sys, tempfile, warnings
from contextlib import contextmanager
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

import watch_smthn.app as appmod
from watch_smthn.app import WatchSmthnApp, _HEADER_NAMES
from watch_smthn.config import load_config, load_sources, _normalize_source, _merge_iptv_urls
from watch_smthn.favorites import toggle_favorite
from watch_smthn.models import EntryMeta
from watch_smthn.m3u_parser import (
    _stream_playlist, _apply_overrides, parse_m3u_content, _is_hls,
)
from textual.widgets import ListView, ListItem, DataTable

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(f"  [{'OK  ' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


def skip(name, why):
    print(f"  [SKIP] {name}  {why}")


def sources(app):
    lv = app.query_one("#source-list", ListView)
    return [(str(c.query("Label").first().content), c.has_class("-active"))
            for c in lv.children if isinstance(c, ListItem)]


def active(app):
    return [t for t, a in sources(app) if a]


def labels(app):
    return [it["label"] for it in app._source_items]


def rows(app):
    t = app.query_one("#channel-table", DataTable)
    return [t.get_row_at(i) for i in range(t.row_count)]


def select(app, label):
    idx = next(i for i, it in enumerate(app._source_items) if it["label"] == label)
    app.current_source_label = label
    app._load_source_group(app._source_items[idx]["indices"])


def titled_entries():
    out = []
    for s in load_sources(load_config()):
        for e in s.get("entries", []):
            if e["meta"].title:
                out.append((s["name"], e))
    return out


@contextmanager
def patched(obj, name, value):
    existed = hasattr(obj, name)
    old = getattr(obj, name, None)
    setattr(obj, name, value)
    try:
        yield
    finally:
        if existed:
            setattr(obj, name, old)
        else:
            delattr(obj, name)


@contextmanager
def patched_env(**values):
    old = {k: os.environ.get(k) for k in values}
    for key, value in values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def unit_normalization():
    print("\n[0] _normalize_source / _merge_iptv_urls (unit)")
    src = _normalize_source({"name": "X", "type": "tv", "urls": [
        "http://a/list.m3u8",
        {"url": "http://b/stream.m3u8", "title": "Titled Row"},
        "", {"url": "  ", "title": "dropped"}, {"title": "no url"},
        {"url": "http://c/x.m3u8"},
    ]})
    check("urls is a full string projection",
          src["urls"] == ["http://a/list.m3u8", "http://b/stream.m3u8", "http://c/x.m3u8"],
          str(src["urls"]))
    check("order + titles preserved in entries",
          [(e["url"], e["meta"].title) for e in src["entries"]] == [
              ("http://a/list.m3u8", None),
              ("http://b/stream.m3u8", "Titled Row"),
              ("http://c/x.m3u8", None)],
          str([(e["url"], e["meta"].title) for e in src["entries"]]))
    check("urls are all str", all(isinstance(u, str) for u in src["urls"]))
    check("entries and urls stay in sync", len(src["urls"]) == len(src["entries"]))
    alltitled = _normalize_source({"name": "Y", "type": "tv", "urls": [
        {"url": "http://s/one.m3u8", "title": "One"},
        {"url": "http://s/two.m3u8", "title": "Two"}]})
    check("all-titled source is not empty for _load_source",
          bool(alltitled["urls"]) and len(alltitled["urls"]) == 2 and
          all(isinstance(u, str) for u in alltitled["urls"]),
          str(alltitled["urls"]))
    check("titled handles survive for type: st",
          _normalize_source({"name": "Twitch", "type": "st",
                             "urls": [{"url": "someone", "title": "Hi"}]})["urls"] == ["someone"])
    try:
        set(src["urls"])
        check("set(urls) hashable", True)
    except TypeError as e:
        check("set(urls) hashable", False, str(e))
    norm = _normalize_source({"name": "iptv", "type": "tv",
                              "urls": ["http://base/list.m3u", {"url": "http://y/s.m3u8", "title": "T"}]})
    try:
        _merge_iptv_urls([norm], ["http://extra/z.m3u"])
        check("_merge_iptv_urls no TypeError", True, f"urls={norm['urls']}")
    except TypeError as e:
        check("_merge_iptv_urls no TypeError", False, str(e))

    meta_src = _normalize_source({"name": "M", "type": "tv", "urls": [
        {"url": "http://a/stream.m3u8", "title": "Titled Row",
         "group": "Cartoons", "country": "US"},
        {"url": "http://b/stream.m3u8", "title": "  ", "group": "", "country": None},
        "http://c/plain.m3u8",
    ]})
    m0, m1, m2 = (e["meta"] for e in meta_src["entries"])
    check("meta carries title/group/country",
          (m0.title, m0.group, m0.country) == ("Titled Row", "Cartoons", "US"),
          str(m0))
    check("blank or null meta values become None",
          (m1.title, m1.group, m1.country) == (None, None, None), str(m1))
    check("plain string entry gets an empty meta",
          (m2.title, m2.group, m2.country) == (None, None, None), str(m2))
    check("meta never leaks into the urls projection",
          meta_src["urls"] == ["http://a/stream.m3u8", "http://b/stream.m3u8",
                               "http://c/plain.m3u8"], str(meta_src["urls"]))


def unit_title_rules():
    print("\n[1] title / group / country rules (unit)")
    hls = "#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:6.000,\nseg1.ts\n"
    chan = ('#EXTM3U\n#EXTINF:-1 group-title="News",CNN\nhttp://x/cnn.m3u8\n'
            '#EXTINF:-1 group-title="Movies",Film\nhttp://y/f.m3u8\n')
    with_country = ('#EXTM3U\n#EXTINF:-1 tvg-country="FR" group-title="News",CNN\n'
                    'http://x/cnn.m3u8\n'
                    '#EXTINF:-1 tvg-country="DE" group-title="Movies",Film\n'
                    'http://y/f.m3u8\n')
    check("HLS detected", _is_hls(hls) and not _is_hls(chan))

    c = _stream_playlist("http://h/s.m3u8", "Src").channels[0]
    check("1 row, no title -> name=src, group blank",
          (c.name, c.group, c.country) == ("Src", "", ""), (c.name, c.group, c.country))
    c = _stream_playlist("http://h/s.m3u8", "Source A",
                         EntryMeta(title="Titled Row")).channels[0]
    check("1 row, titled -> name=title, group=src",
          (c.name, c.group) == ("Titled Row", "Source A"), (c.name, c.group))
    c = _stream_playlist("http://h/s.m3u8", "Dup Row",
                         EntryMeta(title="Dup Row")).channels[0]
    check("1 row, title==src -> group blank (no duplicate)",
          (c.name, c.group) == ("Dup Row", ""), (c.name, c.group))
    c = _stream_playlist("http://h/s.m3u8", "Src",
                         EntryMeta(group="Cartoons")).channels[0]
    check("1 row, explicit group beats the group default",
          (c.name, c.group) == ("Src", "Cartoons"), (c.name, c.group))
    c = _stream_playlist("http://h/s.m3u8", "Src",
                         EntryMeta(title="Row", group="Cartoons", country="US")).channels[0]
    check("1 row, title+group+country land in name/group/country",
          (c.name, c.group, c.country) == ("Row", "Cartoons", "US"), str(c))

    pl = _apply_overrides(parse_m3u_content(chan, "Src"), None)
    check("N rows, no title -> file names/groups/countries",
          [(c.name, c.group) for c in pl.channels] == [("CNN", "News"), ("Film", "Movies")],
          str([(c.name, c.group) for c in pl.channels]))
    pl = _apply_overrides(parse_m3u_content(chan, "Src"), EntryMeta(title="Cartoons"))
    check("N rows, titled -> file names, group=title",
          [(c.name, c.group) for c in pl.channels] == [("CNN", "Cartoons"), ("Film", "Cartoons")],
          str([(c.name, c.group) for c in pl.channels]))
    pl = _apply_overrides(parse_m3u_content(chan, "Src"),
                          EntryMeta(title="From Title", group="From Group"))
    check("N rows, explicit group outranks title",
          [c.group for c in pl.channels] == ["From Group", "From Group"],
          str([c.group for c in pl.channels]))
    pl = _apply_overrides(parse_m3u_content(with_country, "Src"), EntryMeta(country="US"))
    check("N rows, country override -> file groups survive",
          [(c.group, c.country) for c in pl.channels] == [("News", "US"), ("Movies", "US")],
          str([(c.group, c.country) for c in pl.channels]))
    pl = _apply_overrides(parse_m3u_content(with_country, "Src"),
                          EntryMeta(group="Cartoons", country="US"))
    check("N rows, group+country override the file's own values",
          [(c.name, c.group, c.country) for c in pl.channels] ==
          [("CNN", "Cartoons", "US"), ("Film", "Cartoons", "US")],
          str([(c.name, c.group, c.country) for c in pl.channels]))

    entries = titled_entries()
    if entries:
        check("titled entries exist in config", True,
              f"{[e['meta'].title for _, e in entries]}")
    else:
        skip("titled entries exist in config", "config has no titled entries")


def unit_launchers():
    print("\n[J] launchers (platform dispatch)")
    import watch_smthn.launchers as L
    from watch_smthn.models import Player, PlayerType
    from watch_smthn.players import launch_player

    class FakeSubprocess:
        DEVNULL = "DEVNULL"
        CREATE_NO_WINDOW = 0x08000000

        def __init__(self):
            self.calls = {}

        def Popen(self, *args, **kwargs):
            self.calls = {"args": args, "kwargs": kwargs}
            return "PROC"

    fake = FakeSubprocess()
    url = "http://example.invalid/s.m3u8?token=abc&exp=999"

    with patched(L, "subprocess", fake), patched(L.sys, "platform", "linux"):
        result = L.spawn(["mpv", "--no-terminal", url])
    kw = fake.calls["kwargs"]
    check("J spawn passes argv as a single list",
          fake.calls["args"] == (["mpv", "--no-terminal", url],),
          str(fake.calls["args"]))
    check("J spawn on unix is shell=False and detached",
          kw.get("shell") is False and kw.get("start_new_session") is True, str(kw))
    check("J spawn returns the Popen result", result == "PROC", str(result))

    with patched(L, "subprocess", fake), patched(L.sys, "platform", "win32"):
        L.spawn(["mpv", url])
    kw = fake.calls["kwargs"]
    check("J spawn on win32 keeps argv and adds no shell",
          fake.calls["args"] == (["mpv", url],) and "shell" not in kw
          and "start_new_session" not in kw, str(fake.calls))
    check("J spawn on win32 suppresses the console window",
          kw.get("creationflags") == fake.CREATE_NO_WINDOW, str(kw))

    absent = L.resolve_executable("definitely-not-a-real-binary-zz")
    check("J resolve_executable returns None for an absent binary",
          absent is None, str(absent))

    root = Path(tempfile.mkdtemp(prefix="known-install-"))
    (root / "VideoLAN" / "VLC").mkdir(parents=True)
    planted = root / "VideoLAN" / "VLC" / "vlc.exe"
    planted.write_text("")
    known_env = {"ProgramFiles": str(root),
                 "ProgramFiles(x86)": None,
                 "LOCALAPPDATA": None}
    with patched(L.shutil, "which", lambda name: None), patched_env(**known_env):
        resolved = L.resolve_executable("vlc")
    check("J resolve_executable falls back to a known install path",
          resolved == str(planted), str(resolved))

    bindir = Path(tempfile.mkdtemp(prefix="bindir-"))
    planted_mpv = bindir / ("mpv.exe" if os.name == "nt" else "mpv")
    planted_mpv.write_text("")
    planted_mpv.chmod(0o755)
    saved_path = os.environ.get("PATH", "")
    try:
        os.environ["PATH"] = str(bindir) + os.pathsep + saved_path
        from watch_smthn.players import DEFAULT_PLAYERS, find_available_players
        discovered = {p.name: p for p in find_available_players()}
    finally:
        os.environ["PATH"] = saved_path
    mpv_entry = discovered.get("MPV")
    check("J discovery returns a resolved absolute path",
          mpv_entry is not None and Path(mpv_entry.command[0]).is_file(),
          str(None if mpv_entry is None else mpv_entry.command[0]))
    check("J DEFAULT_PLAYERS keeps its unresolved command",
          DEFAULT_PLAYERS[0].command == ["mpv"], str(DEFAULT_PLAYERS[0].command))

    ghost = Player(name="Ghost", player_type=PlayerType.MPV,
                   command=["definitely-not-a-real-binary-zz"])
    raised = False
    try:
        launch_player(ghost, url)
    except FileNotFoundError:
        raised = True
    except OSError:
        raised = False
    check("J launch_player surfaces a missing binary",
          raised, "FileNotFoundError expected")

    with patched(L, "subprocess", fake), patched(L.sys, "platform", "linux"):
        launch_player(Player(name="MPV", player_type=PlayerType.MPV,
                             command=["mpv"], args=["--no-terminal"]), url)
    check("J '&' survives as one argv element through launch_player",
          fake.calls["args"] == (["mpv", "--no-terminal", url],),
          str(fake.calls["args"]))

    with patched(L, "subprocess", fake), patched(L.sys, "platform", "linux"):
        L.open_url("https://example.com/watch")
    check("J open_url on unix uses xdg-open",
          fake.calls["args"] == (["xdg-open", "https://example.com/watch"],),
          str(fake.calls["args"]))

    started = []
    with patched(L.os, "startfile", started.append), patched(L.sys, "platform", "win32"):
        L.open_url("https://example.com/watch")
    check("J open_url on win32 uses os.startfile",
          started == ["https://example.com/watch"], str(started))

    config_path = Path("/tmp/watch-smthn-editor-test.yaml")

    with patched(L, "subprocess", fake), patched(L.sys, "platform", "linux"), \
            patched(L.shutil, "which", lambda name: None), \
            patched_env(VISUAL=None, EDITOR="code --wait"):
        L.open_in_editor(config_path)
    check("J editor with no terminal splits EDITOR into argv",
          fake.calls["args"] == (["code", "--wait", str(config_path)],),
          str(fake.calls["args"]))

    with patched(L, "subprocess", fake), patched(L.sys, "platform", "linux"), \
            patched(L.shutil, "which",
                    lambda name: "/usr/bin/kitty" if name == "kitty" else None), \
            patched_env(VISUAL=None, EDITOR="nano"):
        L.open_in_editor(config_path)
    check("J editor under kitty omits -e",
          fake.calls["args"] == (["kitty", "nano", str(config_path)],),
          str(fake.calls["args"]))

    with patched(L, "subprocess", fake), patched(L.sys, "platform", "linux"), \
            patched(L.shutil, "which",
                    lambda name: "/usr/bin/xterm" if name == "xterm" else None), \
            patched_env(VISUAL=None, EDITOR="nano"):
        L.open_in_editor(config_path)
    check("J editor under another terminal passes -e",
          fake.calls["args"] == (["xterm", "-e", "nano", str(config_path)],),
          str(fake.calls["args"]))

    browser = Player(name="Open in browser", player_type=PlayerType.WEB)
    with patched(L, "subprocess", fake), patched(L.sys, "platform", "linux"):
        launch_player(browser, "https://example.com/watch")
    check("J browser player on unix routes through open_url",
          fake.calls["args"] == (["xdg-open", "https://example.com/watch"],),
          str(fake.calls["args"]))

    started.clear()
    with patched(L.os, "startfile", started.append), patched(L.sys, "platform", "win32"):
        launch_player(browser, "https://example.com/watch")
    check("J browser player on win32 routes through os.startfile",
          started == ["https://example.com/watch"], str(started))

    package = Path(__file__).resolve().parents[1] / "watch_smthn"
    offenders = []
    for path in sorted(package.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for token in ("nohup", "/dev/null", "shell=True"):
            if token in text:
                offenders.append(f"{path.name}:{token}")
    check("J no nohup, /dev/null or shell=True left in the package",
          not offenders, str(offenders))

    carriers = [p.name for p in sorted(package.rglob("*.py"))
                if "xdg-open" in p.read_text(encoding="utf-8")]
    check("J xdg-open lives only in launchers.py",
          carriers == ["launchers.py"], str(carriers))


def unit_config_overrides():
    print("\n[L] config overrides (player_paths / editor)")
    import watch_smthn.launchers as L
    from watch_smthn.config import get_editor, get_player_paths
    from watch_smthn.players import DEFAULT_PLAYERS, find_available_players

    choco = "C:\\ProgramData\\chocolatey\\lib\\mpv.install\\tools\\mpv.exe"
    parsed = get_player_paths({"player_paths": {
        "mpv": choco,
        "vlc": "  /mnt/c/Program Files/VideoLAN/VLC/vlc.exe  ",
        "ffplay": "",
        "": "ignored",
    }})
    check("L player_paths keeps real entries", set(parsed) == {"mpv", "vlc"}, str(sorted(parsed)))
    check("L player_paths strips whitespace",
          parsed["vlc"] == "/mnt/c/Program Files/VideoLAN/VLC/vlc.exe", repr(parsed["vlc"]))
    check("L player_paths ignores a non-mapping",
          get_player_paths({"player_paths": ["mpv"]}) == {}, "not a dict")
    check("L player_paths defaults to empty", get_player_paths({}) == {}, "absent")

    check("L editor comes from config",
          get_editor({"editor": "  code --wait  "}) == "code --wait",
          repr(get_editor({"editor": "  code --wait  "})))
    check("L editor is None when absent or blank",
          get_editor({}) is None and get_editor({"editor": "   "}) is None, "absent/blank")

    with patched(L.sys, "platform", "linux"):
        check("L windows drive path maps to /mnt",
              L.normalize_path(choco) == "/mnt/c/ProgramData/chocolatey/lib/mpv.install/tools/mpv.exe",
              L.normalize_path(choco))
        check("L forward slash drive path maps too",
              L.normalize_path("C:/Program Files/VLC/vlc.exe") == "/mnt/c/Program Files/VLC/vlc.exe",
              L.normalize_path("C:/Program Files/VLC/vlc.exe"))
        check("L bare names and unix paths pass through",
              L.normalize_path("mpv") == "mpv" and L.normalize_path("/usr/bin/vim") == "/usr/bin/vim",
              f"{L.normalize_path('mpv')} {L.normalize_path('/usr/bin/vim')}")

        found = find_available_players(DEFAULT_PLAYERS, {"mpv": choco})
        mpv = next((p for p in found if p.name == "MPV"), None)
        check("L player_paths override beats discovery",
              mpv is not None and mpv.command[0] == L.normalize_path(choco),
              "MPV not listed" if mpv is None else mpv.command[0])

        ghost = "/mnt/c/definitely/not/installed/mpv.exe"
        ghosted = find_available_players(DEFAULT_PLAYERS, {"mpv": ghost})
        ghost_entry = next((p for p in ghosted if p.name == "MPV"), None)
        check("L override is used without an existence check",
              ghost_entry is not None and not Path(ghost).exists() and ghost_entry.command[0] == ghost,
              "MPV dropped" if ghost_entry is None else ghost_entry.command[0])

        named = find_available_players(DEFAULT_PLAYERS, {"MPV": choco})
        entry = next((p for p in named if p.name == "MPV"), None)
        check("L override may be keyed by player name",
              entry is not None and entry.command[0].startswith("/mnt/c/"),
              "MPV not listed" if entry is None else entry.command[0])

    with patched(L.sys, "platform", "win32"):
        kept = L.normalize_path("C:\\Program Files\\VLC\\vlc.exe")
    check("L windows build keeps drive paths", kept == "C:\\Program Files\\VLC\\vlc.exe", kept)
    check("L DEFAULT_PLAYERS stays unresolved",
          DEFAULT_PLAYERS[0].command == ["mpv"], str(DEFAULT_PLAYERS[0].command))

    class FakeSubprocess:
        DEVNULL = "DEVNULL"
        CREATE_NO_WINDOW = 0x08000000

        def __init__(self):
            self.calls = {}

        def Popen(self, *args, **kwargs):
            self.calls = {"args": args, "kwargs": kwargs}
            return "PROC"

    fake = FakeSubprocess()
    config_path = Path("/tmp/watch-smthn-editor-override.yaml")
    started = []
    with patched(L, "subprocess", fake), patched(L.sys, "platform", "win32"), \
            patched(L.os, "startfile", started.append), \
            patched_env(VISUAL="nano", EDITOR="nano"):
        L.open_in_editor(config_path, "code --wait")
    check("L configured editor becomes argv",
          fake.calls["args"] == (["code", "--wait", str(config_path)],),
          str(fake.calls["args"]))
    check("L configured editor skips os.startfile", started == [], str(started))
    check("L configured editor skips the terminal probe",
          not any(t in str(fake.calls["args"]) for t in ("kitty", "xterm", "alacritty")),
          str(fake.calls["args"]))


def unit_debug():
    print("\n[M] debug logging (--debug)")
    from watch_smthn import debug as D
    from watch_smthn.__main__ import build_parser

    args = build_parser().parse_args([])
    check("M --debug is off by default",
          args.debug is False and args.debug_log is None, f"{args.debug} {args.debug_log}")
    args = build_parser().parse_args(["--debug", "--debug-log", "/tmp/x.log"])
    check("M --debug and --debug-log parse",
          args.debug is True and args.debug_log == "/tmp/x.log",
          f"{args.debug} {args.debug_log}")

    with patched_env(WATCH_SMTHN_DEBUG_LOG=None, WATCH_SMTHN_DEBUG=None):
        default = D.default_log_path()
    check("M default log path is outside the repo",
          not str(default).startswith(str(Path.cwd())), str(default))

    D.disable_debug()
    D.dbg("written only while enabled")
    target = Path(tempfile.mkdtemp()) / "nested" / "debug.log"
    try:
        path = D.setup_debug(target)
        check("M setup_debug creates the file",
              path == target and target.exists(), str(path))
        D.dbg("hello from the suite")
        try:
            raise ValueError("boom")
        except ValueError as exc:
            D.dbg_error("something broke", exc)
        body = target.read_text(encoding="utf-8")
        check("M debug log contains the message",
              "hello from the suite" in body, body[-160:])
        check("M debug log contains the exception",
              "ValueError: boom" in body, body[-160:])
    finally:
        D.disable_debug()
    leftover = target.read_text(encoding="utf-8") if target.exists() else ""
    check("M disable_debug stops writing",
          D.is_enabled() is False and "written after disable" not in leftover, "still writing")


def unit_url_validation():
    print("\n[N] URL validation and player diagnostics")
    from watch_smthn.launchers import check_launchable, open_sink, read_tail, summarize

    check("N empty URL is refused",
          check_launchable("") == "this channel has no URL", str(check_launchable("")))
    check("N whitespace URL is refused",
          check_launchable("   ") is not None, str(check_launchable("   ")))
    bare = check_launchable("example.com/live/stream.m3u8")
    check("N missing scheme is refused",
          bool(bare) and bare.startswith("the URL is missing"), str(bare))
    odd = check_launchable("javascript:alert(1)")
    check("N unsupported scheme is refused",
          bool(odd) and odd.startswith("unsupported scheme"), str(odd))
    check("N host-less URL is refused",
          check_launchable("http://") == "the URL has no host", str(check_launchable("http://")))
    good = ["https://example.com/a.m3u8",
            "http://192.168.1.9:8080/live/x.ts",
            "rtmp://host/app/key",
            "file:///tmp/v.mkv"]
    check("N well formed URLs are allowed",
          all(check_launchable(u) is None for u in good),
          str([u for u in good if check_launchable(u)]))

    sink = open_sink()
    sink.write(b"quiet line\n[ffmpeg] something failed: no such file\nlast words\n")
    sink.flush()
    tail = read_tail(sink)
    sink.close()
    check("N read_tail returns the captured stderr",
          "no such file" in tail, repr(tail[-80:]))
    check("N summarize picks the failure line",
          "no such file" in summarize(tail), repr(summarize(tail)))
    one = summarize(tail)
    check("N summarize stays on one short line",
          "\n" not in one and len(one) <= 320, repr(one))
    check("N summarize of empty output is empty", summarize("") == "", "not empty")

    from watch_smthn.models import Channel
    from watch_smthn.players import DEFAULT_PLAYERS
    bare_app = WatchSmthnApp()
    notes = []
    capture = lambda msg="", *a, **k: notes.append(str(msg))
    mpv = next(p for p in DEFAULT_PLAYERS if p.name == "MPV")
    with patched(bare_app, "notify", capture):
        bare_app._launch(Channel(name="Broken", url=""), mpv)
    check("N launch refuses a channel with no URL",
          any("Cannot play Broken" in n for n in notes), str(notes))


def unit_reaping():
    print("\n[O] Spawned player reaping")

    class FakeProc:
        def __init__(self, code):
            self.code = code
            self.polls = 0

        def poll(self):
            self.polls += 1
            return self.code

    class Broken:
        def poll(self):
            raise RuntimeError("boom")

    app = WatchSmthnApp()
    app._track(None)
    check("O a null handle is not tracked", app._children == [], str(app._children))

    alive = FakeProc(None)
    dead = FakeProc(0)
    app._track(alive)
    app._track(dead)
    check("O spawned players are tracked",
          app._children == [alive, dead], str(len(app._children)))

    app._reap_children()
    check("O exited players are dropped",
          app._children == [alive], str(len(app._children)))
    check("O survivors are polled again", alive.polls >= 1, str(alive.polls))

    app._children.append(Broken())
    raised = False
    try:
        app._reap_children()
    except Exception:
        raised = True
    check("O a failing poll does not break the reaper", not raised, "raised")
    check("O the failing child is dropped",
          app._children == [alive], str(len(app._children)))

    import inspect
    mounted = inspect.getsource(WatchSmthnApp.on_mount)
    check("O the reaper interval is wired up",
          "set_interval" in mounted and "_reap_children" in mounted,
          "set_interval(5.0, self._reap_children) not found in on_mount")


async def session_main():
    app = WatchSmthnApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(4.0)

        print("\n[A] CSS / boot")
        check("no CSS errors", app._css_has_errors is False, str(app._css_has_errors))
        n_first = len(app.all_channels)
        check("first source loaded", n_first > 0, f"{n_first} channels")

        keybinds = {b.key: b.action for b in WatchSmthnApp.BINDINGS}
        check("config key is ctrl+e",
              keybinds.get("ctrl+e") == "edit_config", str(sorted(keybinds)))
        check("no ctrl+, keybinding left",
              "ctrl+comma" not in keybinds, str(sorted(keybinds)))

        print("\n[B] search (7 cases)")
        total = len(app.all_channels)
        app.current_category = "All"
        app.current_search = ""
        app._filter_channels()
        check("1 empty search returns everything", len(app.filtered_channels) == total)
        app.current_search = "cnn"
        app._filter_channels()
        n_cnn = len(app.filtered_channels)
        check("2 substring 'cnn' matches", 0 < n_cnn <= total, f"{n_cnn} rows")
        app.current_search = "CNN"
        app._filter_channels()
        check("3 case-insensitive", len(app.filtered_channels) == n_cnn)
        sample = app.all_channels[0]
        app.current_search = sample.group if sample.group else sample.name[:4]
        app._filter_channels()
        check("4 search matches group/name", len(app.filtered_channels) > 0)
        app.current_search = "country:us"
        app._filter_channels()
        check("5 param country:us", len(app.filtered_channels) > 0, f"{len(app.filtered_channels)} rows")
        grp = next((c.group for c in app.all_channels if c.group), "")
        app.current_search = f"group:{grp}"
        app._filter_channels()
        check("6 param group:<name>", len(app.filtered_channels) > 0, f"group={grp!r}")
        app.current_search = "zzzznotarealchannel"
        app._filter_channels()
        check("7 no-match returns 0", len(app.filtered_channels) == 0)
        app.current_search = ""
        app._filter_channels()

        print("\n[C] source switching + -active (all sources, discovered)")
        for label in labels(app):
            select(app, label)
            await pilot.pause(3.5)
            check(f"switch to {label!r}",
                  active(app) == [label] and len(app.all_channels) > 0,
                  f"rows={len(app.all_channels)} active={active(app)}")

        print("\n[D] titled HLS row discovered from config")
        found = titled_entries()
        if not found:
            skip("titled HLS row", "no titled entry in config")
        else:
            src_name, entry = found[0]
            select(app, src_name)
            await pilot.pause(3.5)
            matches = [c for c in app.all_channels if c.url == entry["url"]]
            check("titled url yields exactly 1 row", len(matches) == 1, f"{len(matches)} rows")
            if matches:
                c = matches[0]
                meta = entry["meta"]
                expect_group = meta.group or ("" if meta.title == src_name else src_name)
                check("row name is the title", c.name == meta.title, f"{c.name!r}")
                check("row group honours explicit group, else source name",
                      c.group == expect_group, f"{c.group!r}")
                check("row country honours explicit country",
                      c.country == (meta.country or ""), f"{c.country!r}")
                check("marked hls", c.extra.get("hls") is True)
            r = rows(app)
            check("titled row rendered in table",
                  any(entry["meta"].title in str(x[0]) for x in r),
                  f"table rows={len(r)}")
            if matches:
                drawn = [tuple(x[:3]) for x in r
                         if entry["meta"].title in str(x[0])]
                check("titled row renders all three overridden cells",
                      len(drawn) == 1 and drawn[0][1] == expect_group
                      and drawn[0][2] == matches[0].country, str(drawn))
            others = [c for c in app.all_channels if c.url != entry["url"]]
            check("untitled sibling rows untouched",
                  all(not c.extra.get("hls") for c in others), f"{len(others)} sibling rows")

        print("\n[E] favorites round-trip (restored afterwards)")
        first = labels(app)[0]
        select(app, first)
        await pilot.pause(3.5)
        ch = app.all_channels[0]
        was = ch.url in app.favorite_urls
        toggle_favorite(app.favorite_urls, ch.url)
        app._mark_favorites()
        await app._build_sidebar()
        cats = category_labels(app)
        check("favorites category appears", any("Favorites" in c for c in cats))
        app.current_category = "★ Favorites"
        app._filter_channels()
        check("favorites filter non-empty", len(app.filtered_channels) > 0)
        toggle_favorite(app.favorite_urls, ch.url)
        app._mark_favorites()
        app.current_category = "All"
        app._filter_channels()
        await app._build_sidebar()
        check("favorite state restored", (ch.url in app.favorite_urls) == was)

        print("\n[K] launch outcome reporting")
        from watch_smthn.models import Channel
        from watch_smthn.players import DEFAULT_PLAYERS
        browser = next(p for p in DEFAULT_PLAYERS
                       if p.player_type.value == "web")
        chan = Channel(name="ReportChan", url="https://example.com/watch")
        notes = []
        capture = lambda msg="", *a, **k: notes.append(str(msg))

        with patched(app, "notify", capture), \
                patched(appmod, "launch_player", lambda p, u, sink=None: None):
            app._launch(chan, browser)
        check("K launch without a handle still reports success",
              any("Playing ReportChan in Open in browser" in n for n in notes),
              str(notes))

        def missing(p, u, sink=None):
            raise FileNotFoundError(2, "No such file or directory", "mpv")

        notes.clear()
        with patched(app, "notify", capture), \
                patched(appmod, "launch_player", missing):
            app._launch(chan, browser)
        check("K missing binary names the binary in the toast",
              bool(notes) and "mpv not found" in notes[-1], str(notes))


def fake_config(extra_sources=None, twitch_urls=None):
    cfg = copy.deepcopy(load_config())
    srcs = copy.deepcopy(cfg.get("sources", []))
    if twitch_urls is not None:
        for s in srcs:
            if s.get("name") == "Twitch":
                s["urls"] = list(twitch_urls)
    if extra_sources:
        srcs.extend(copy.deepcopy(extra_sources))
    cfg["sources"] = srcs
    return cfg


appmod.save_custom_source_to_config = lambda cfg, entry: None
appmod.save_handle_to_config = lambda cfg, platform, handle: None


async def add_source_main():
    print("\n[F] add-source A")
    app = WatchSmthnApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(4.0)
        before = len(app.all_channels)
        first_label = labels(app)[0]
        appmod.load_config = lambda: fake_config(extra_sources=[
            {"name": "ZZZ Test", "type": "tv",
             "urls": [{"url": "http://example.invalid/x.m3u", "title": "Titled Row"}],
             "categories": True}])
        app._on_add_source({"name": "ZZZ Test", "type": "tv",
                            "urls": ["http://example.invalid/x.m3u"]})
        await pilot.pause(1.5)
        s = sources(app)
        check("A current source untouched", len(app.all_channels) == before,
              f"n={len(app.all_channels)} (was {before})")
        check("A still active on same source", [t for t, a in s if a] == [first_label],
              str([t for t, a in s if a]))
        check("A new source appended last", labels(app)[-1] == "ZZZ Test", str(labels(app)))
        select(app, "ZZZ Test")
        await pilot.pause(4.0)
        r = rows(app)
        check("A titled-only source loads (not treated as empty by _load_source)",
              len(r) == 1, f"{len(r)} rows {r}")
        if r:
            check("A untitled fetch fallback uses the title",
                  r[0][0] == "Titled Row" and r[0][1] == "ZZZ Test", str(r))

    print("\n[G] add-source B / C")
    app = WatchSmthnApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(4.0)
        if "Twitch" not in labels(app):
            skip("B", "no Twitch source in config")
        else:
            select(app, "Twitch")
            await pilot.pause(2.0)
            appmod.load_config = lambda: fake_config(
                twitch_urls=["streamerone", "streamertwo", "streamerthree"])
            app._on_add_source({"platform": "twitch", "handles": ["streamerthree"]})
            await pilot.pause(1.5)
            names = [c.name for c in app.all_channels]
            check("B handle added while on Twitch",
                  names == ["streamerone", "streamertwo", "streamerthree"] and active(app) == ["Twitch"],
                  f"{names} active={active(app)}")

    app = WatchSmthnApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(4.0)
        before = len(app.all_channels)
        first_label = labels(app)[0]
        appmod.load_config = lambda: fake_config(
            twitch_urls=["streamerone", "streamertwo", "streamerthree"])
        app._on_add_source({"platform": "twitch", "handles": ["streamerthree"]})
        await pilot.pause(1.5)
        check("C other source untouched",
              len(app.all_channels) == before and active(app) == [first_label],
              f"n={len(app.all_channels)} (was {before}) active={active(app)}")


async def meta_main():
    print("\n[H] per-URL group / country")
    app = WatchSmthnApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(4.0)
        appmod.load_config = lambda: fake_config(extra_sources=[
            {"name": "ZZZ Meta", "type": "tv",
             "urls": [{"url": "http://example.invalid/meta.m3u",
                       "title": "Meta Row", "group": "Cartoons",
                       "country": "US"}],
             "categories": True}])
        app._on_add_source({"name": "ZZZ Meta", "type": "tv",
                            "urls": ["http://example.invalid/meta.m3u"]})
        await pilot.pause(1.5)
        if "ZZZ Meta" not in labels(app):
            skip("H", "source not appended")
            return
        select(app, "ZZZ Meta")
        await pilot.pause(4.0)
        r = rows(app)
        check("H fetch fallback fills name/group/country cells",
              len(r) == 1 and tuple(r[0][:3]) == ("Meta Row", "Cartoons", "US"),
              str([tuple(x) for x in r]))
        cats = category_labels(app)
        check("H group becomes a sidebar category", "Cartoons" in cats, str(cats))


def category_labels(app):
    return [str(c.query("Label").first().content) for c in
            app.query_one("#category-list", ListView).children if isinstance(c, ListItem)]


def header_labels(app):
    table = app.query_one("#channel-table", DataTable)
    return [getattr(c.label, "plain", str(c.label)) for c in table.ordered_columns]


def click_header(app, idx):
    table = app.query_one("#channel-table", DataTable)
    col = table.ordered_columns[idx]
    app.on_data_table_header_selected(DataTable.HeaderSelected(table, col.key, idx, col.label))


def cells_match(app):
    r = rows(app)
    n = min(len(r), len(app.filtered_channels))
    return n == len(r) == len(app.filtered_channels) and all(
        str(app.filtered_channels[i].name) in str(r[i][0]) for i in range(n))


async def order_main():
    print("\n[I] category + table ordering")
    app = WatchSmthnApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(4.0)

        cats = category_labels(app)
        start = 1 if cats and "Favorites" in cats[0] else 0
        fav_idx = next((i for i, c in enumerate(cats) if "Favorites" in c), None)
        if fav_idx is None:
            skip("I Favorites pinned first when present", "no Favorites source in config")
        else:
            check("I Favorites pinned first when present", fav_idx == 0, str(cats[:2]))
        check("I All pinned before every group",
              len(cats) > start and cats[start] == "All", cats[:start + 1])
        body = cats[start + 1:]
        check("I categories sorted A-Z",
              body == sorted(body, key=str.casefold), body)

        names = [c.name for c in app.filtered_channels]
        check("I default table order is A-Z",
              names == sorted(names, key=str.casefold), names[:5])
        check("I rendered rows match filtered_channels (default)", cells_match(app),
              f"{len(rows(app))} rows / {len(app.filtered_channels)} channels")

        click_header(app, 1)
        check("I first Group click sorts ascending",
              app._sort == 1 and app._sort_desc is False,
              f"sort={app._sort} desc={app._sort_desc}")
        check("I header shows Group marker", header_labels(app)[1] == "Group ▲",
              str(header_labels(app)))
        groups = [c.group for c in app.filtered_channels]
        check("I group column sorted ascending",
              groups == sorted(groups, key=str.casefold), groups[:5])
        check("I rendered rows match filtered_channels (sorted)", cells_match(app),
              f"first={app.filtered_channels[0].name!r}")

        click_header(app, 1)
        check("I second Group click sorts descending",
              app._sort == 1 and app._sort_desc is True,
              f"sort={app._sort} desc={app._sort_desc}")
        check("I header shows Group marker",
              header_labels(app)[1] == "Group ▼", str(header_labels(app)))
        groups = [c.group for c in app.filtered_channels]
        check("I group column sorted descending",
              groups == sorted(groups, key=str.casefold, reverse=True), groups[:5])

        click_header(app, 1)
        check("I third Group click clears the sort",
              app._sort is None and app._sort_desc is False,
              f"sort={app._sort} desc={app._sort_desc}")
        check("I headers return to plain", header_labels(app) == list(_HEADER_NAMES),
              str(header_labels(app)))
        names = [c.name for c in app.filtered_channels]
        check("I default A-Z order restored",
              names == sorted(names, key=str.casefold), names[:5])

        click_header(app, 2)
        check("I Country click sets ascending",
              app._sort == 2 and app._sort_desc is False,
              f"sort={app._sort} desc={app._sort_desc}")
        others = [l for l in labels(app) if l != app.current_source_label]
        select(app, others[0] if others else app.current_source_label)
        await pilot.pause(4.0)
        check("I sort survives a source switch",
              app._sort == 2 and app._sort_desc is False,
              f"sort={app._sort} desc={app._sort_desc}")
        check("I header still marks Country",
              header_labels(app)[2] == "Country ▲", str(header_labels(app)))
        countries = [c.country for c in app.filtered_channels]
        check("I new source re-sorted by country",
              countries == sorted(countries, key=str.casefold), countries[:5])
        check("I rendered rows still match after switch", cells_match(app),
              f"{len(app.filtered_channels)} channels")


async def main():
    unit_normalization()
    unit_title_rules()
    unit_launchers()
    unit_config_overrides()
    unit_debug()
    unit_url_validation()
    unit_reaping()
    await session_main()
    await order_main()
    await add_source_main()
    await meta_main()
    passed = sum(1 for _, ok in RESULTS if ok)
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{'='*60}\n{passed}/{len(RESULTS)} passed")
    if failed:
        print("FAILED:")
        for n in failed:
            print(f"  - {n}")
        sys.exit(1)
    print("ALL PASS")

asyncio.run(main())
