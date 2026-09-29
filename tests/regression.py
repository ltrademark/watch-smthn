import asyncio, sys, copy, warnings
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

    check("titled entries exist in config", bool(titled_entries()),
          f"{[e['meta'].title for _, e in titled_entries()]}")


async def session_main():
    app = WatchSmthnApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(4.0)

        print("\n[A] CSS / boot")
        check("no CSS errors", app._css_has_errors is False, str(app._css_has_errors))
        n_first = len(app.all_channels)
        check("first source loaded", n_first > 0, f"{n_first} channels")

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
        check("I Favorites pinned first when present", start == 1, cats[:2])
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
