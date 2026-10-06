"""Main TUI application for watch somethin."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Optional

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.events import Click, Key, Resize
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
)

from .config import (
    _find_config,
    get_custom_players,
    load_config,
    load_sources,
    load_streamers_from_sources,
    save_custom_source_to_config,
    save_handle_to_config,
)
from .favorites import load_favorites, toggle_favorite
from .launchers import open_in_editor, spawn
from .m3u_parser import load_playlist_auto
from .models import Channel, ContentType, EntryMeta, Player, Playlist
from .players import DEFAULT_PLAYERS, find_available_players, launch_player
from .streamers import build_streamlink_command

_SEARCH_PARAM_RE = re.compile(r"^(country|lang|group)\s*[:=]\s*(\S.*)$", re.IGNORECASE)
_HEADER_NAMES = ("Name", "Group", "Country")


class PlayerSelectScreen(ModalScreen[Optional[Player]]):
    """Modal screen for selecting which player to use."""

    CSS = """
    PlayerSelectScreen {
        align: center middle;
    }
    #player-dialog {
        width: 50;
        height: auto;
        max-height: 80%;
        border: round $primary;
        background: #0a0a0a;
        padding: 1 2;
    }
    #player-dialog Label {
        text-align: center;
        width: 100%;
        margin-bottom: 1;
        color: white;
    }
    #player-list {
        height: auto;
        max-height: 40;
    }
    #player-list > ListItem {
        padding: 0 2;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, players: list[Player], channel_name: str) -> None:
        super().__init__()
        self.players = players
        self.channel_name = channel_name

    def compose(self) -> ComposeResult:
        with Vertical(id="player-dialog"):
            yield Label(f"Play [b]{self.channel_name}[/b] with:")
            with ListView(id="player-list"):
                for p in self.players:
                    safe_id = p.name.lower().replace(" ", "-").replace(".", "")
                    yield ListItem(Label(p.name), id=f"player-{safe_id}")

    @on(ListView.Selected)
    def on_player_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if 0 <= idx < len(self.players):
            self.dismiss(self.players[idx])

    def action_cancel(self) -> None:
        self.dismiss(None)


class AddSourceScreen(ModalScreen[Optional[dict[str, Any]]]):
    """Modal screen for adding a streamer or custom TV source."""

    CSS = """
    AddSourceScreen {
        align: center middle;
        background: #000000cc;
    }
    #add-source-dialog {
        width: 54;
        height: auto;
        max-height: 80%;
        border: round $primary;
        background: #0a0a0a;
        padding: 2 2 1 2;
    }
    #add-source-title {
        width: 100%;
        text-align: center;
        text-style: bold;
        color: white;
        margin-bottom: 2;
    }
    #add-source-dialog Label {
        width: 100%;
        color: $text-muted;
        margin-bottom: 1;
    }
    #platform-grid {
        height: auto;
        margin-bottom: 2;
    }
    #platform-grid Horizontal {
        height: 3;
        margin-bottom: 1;
    }
    #platform-grid Static {
        width: 1fr;
        height: 3;
        content-align: center middle;
        text-align: center;
        background: #1a1a1a;
        color: $text-muted;
        border: none;
        margin-right: 1;
    }
    #platform-grid Static.-selected {
        background: $primary;
        color: white;
    }
    #add-source-dialog Input {
        margin-bottom: 1;
        background: #1a1a1a;
        border: none;
        color: white;
        height: 3;
        padding: 1 2;
    }
    #add-source-dialog Input:focus {
        background: #1a1a1a;
        border: none;
    }
    #url-list {
        height: auto;
        margin-bottom: 1;
    }
    #handle-list {
        height: auto;
        margin-bottom: 1;
    }
    #streamlink-fields {
        height: auto;
    }
    #custom-fields {
        height: auto;
    }
    #url-list Input {
        margin-bottom: 0;
    }
    .url-row {
        height: 3;
        margin-bottom: 1;
    }
    .url-row Input {
        width: 1fr;
        margin-right: 1;
        margin-bottom: 0;
    }
    .url-row Button {
        width: 5;
        height: 3;
        border: none;
        background: #2a2a2a;
        color: $text-muted;
        min-width: 5;
        padding: 0;
        content-align: center middle;
    }
    #add-url-btn {
        width: 100%;
        height: 3;
        border: none;
        background: #1a1a1a;
        color: $text-muted;
        margin-bottom: 1;
    }
    .handle-row {
        height: 3;
        margin-bottom: 1;
    }
    .handle-row Input {
        width: 1fr;
        margin-right: 1;
        margin-bottom: 0;
    }
    .handle-row Button {
        width: 5;
        height: 3;
        border: none;
        background: #2a2a2a;
        color: $text-muted;
        min-width: 5;
        padding: 0;
        content-align: center middle;
    }
    #add-handle-btn {
        width: 100%;
        height: 3;
        border: none;
        background: #1a1a1a;
        color: $text-muted;
        margin-bottom: 1;
    }
    #add-source-buttons {
        height: 3;
        margin-top: 2;
        width: 100%;
    }
    #add-source-buttons Button {
        width: 1fr;
        height: 3;
        margin-right: 1;
        border: none;
    }
    #add-source-buttons Button:last-child {
        margin-right: 0;
    }
    #cancel-btn {
        background: #1a1a1a;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    STREAMLINK_PLATFORMS = ["twitch", "youtube", "bilibili", "dailymotion", "afreecatv"]
    PLATFORMS = STREAMLINK_PLATFORMS + ["custom"]

    def __init__(self) -> None:
        super().__init__()
        self.selected_platform = "twitch"

    def compose(self) -> ComposeResult:
        with Vertical(id="add-source-dialog"):
            yield Label("Add Source", id="add-source-title")
            yield Label("Platform:")
            with Vertical(id="platform-grid"):
                row1 = self.PLATFORMS[:3]
                row2 = self.PLATFORMS[3:]
                with Horizontal():
                    for p in row1:
                        yield Static(p, id=f"plat-{p}")
                with Horizontal():
                    for p in row2:
                        yield Static(p, id=f"plat-{p}")
            with Vertical(id="streamlink-fields"):
                with Vertical(id="handle-list"):
                    with Horizontal(classes="handle-row"):
                        yield Input(placeholder="Handle / Username", classes="handle-input")
                        yield Button("\u00d7", classes="remove-handle-btn")
                yield Button("+ Add handle", id="add-handle-btn")
            with Vertical(id="custom-fields"):
                yield Label("Source Name:")
                yield Input(placeholder="e.g. My IPTV", id="source-name-input")
                yield Label("URLs:")
                with Vertical(id="url-list"):
                    with Horizontal(classes="url-row"):
                        yield Input(placeholder="https://example.com/playlist.m3u", classes="url-input")
                        yield Button("\u00d7", classes="remove-url-btn")
                yield Button("+ Add URL", id="add-url-btn")
            with Horizontal(id="add-source-buttons"):
                yield Button("Save", id="save-btn", variant="primary")
                yield Button("Cancel", id="cancel-btn", variant="default")

    def on_mount(self) -> None:
        self._update_tile_styles()
        self._toggle_fields()

    def _update_tile_styles(self) -> None:
        for p in self.PLATFORMS:
            tile = self.query_one(f"#plat-{p}", Static)
            if p == self.selected_platform:
                tile.add_class("-selected")
            else:
                tile.remove_class("-selected")

    def _toggle_fields(self) -> None:
        is_custom = self.selected_platform == "custom"
        streamlink = self.query_one("#streamlink-fields")
        custom = self.query_one("#custom-fields")
        streamlink.display = not is_custom
        custom.display = is_custom

    def on_click(self, event: Click) -> None:
        target = event.widget
        if isinstance(target, Static) and target.id and target.id.startswith("plat-"):
            platform = target.id.replace("plat-", "")
            if platform in self.PLATFORMS:
                self.selected_platform = platform
                self._update_tile_styles()
                self._toggle_fields()

    @on(Button.Pressed, "#add-url-btn")
    def on_add_url(self) -> None:
        url_list = self.query_one("#url-list")
        row = Horizontal(classes="url-row")
        url_list.mount(row)
        row.mount(
            Input(placeholder="https://example.com/playlist.m3u", classes="url-input"),
            Button("\u00d7", classes="remove-url-btn"),
        )

    @on(Button.Pressed, ".remove-url-btn")
    def on_remove_url(self, event: Button.Pressed) -> None:
        row = event.button.parent
        if row and isinstance(row, Horizontal):
            url_list = self.query_one("#url-list")
            if len(url_list.query(Horizontal)) > 1:
                row.remove()

    @on(Button.Pressed, "#add-handle-btn")
    def on_add_handle(self) -> None:
        handle_list = self.query_one("#handle-list")
        row = Horizontal(classes="handle-row")
        handle_list.mount(row)
        row.mount(
            Input(placeholder="Handle / Username", classes="handle-input"),
            Button("\u00d7", classes="remove-handle-btn"),
        )

    @on(Button.Pressed, ".remove-handle-btn")
    def on_remove_handle(self, event: Button.Pressed) -> None:
        row = event.button.parent
        if row and isinstance(row, Horizontal):
            handle_list = self.query_one("#handle-list")
            if len(handle_list.query(Horizontal)) > 1:
                row.remove()

    @on(Button.Pressed, "#save-btn")
    def on_save(self) -> None:
        if self.selected_platform == "custom":
            self._save_custom()
        else:
            self._save_streamlink()

    def _save_streamlink(self) -> None:
        handles = []
        for inp in self.query(".handle-input"):
            handle = inp.value.strip()
            if handle:
                handles.append(handle)
        if not handles:
            self.notify("At least one handle is required", severity="error")
            return
        entry: dict[str, Any] = {
            "handles": handles,
            "platform": self.selected_platform,
        }
        self.dismiss(entry)

    def _save_custom(self) -> None:
        name = self.query_one("#source-name-input", Input).value.strip()
        if not name:
            self.notify("Source name is required", severity="error")
            return
        urls = []
        for inp in self.query(".url-input"):
            url = inp.value.strip()
            if url:
                urls.append(url)
        if not urls:
            self.notify("At least one URL is required", severity="error")
            return
        entry: dict[str, Any] = {
            "name": name,
            "type": "tv",
            "urls": urls,
            "categories": True,
        }
        self.dismiss(entry)

    @on(Button.Pressed, "#cancel-btn")
    def action_cancel(self) -> None:
        self.dismiss(None)


class ChannelRow:
    """Wraps a channel for display in DataTable."""

    def __init__(self, channel: Channel) -> None:
        self.channel = channel


class PlayableDataTable(DataTable):
    """DataTable subclass that supports double-click to play."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._last_click_time: float = 0.0
        self._last_click_y: int = -1

    def on_click(self, event: Click) -> None:
        now = time.monotonic()
        y = event.y
        if y == self._last_click_y and (now - self._last_click_time) < 0.4:
            self._last_click_time = 0.0
            self._last_click_y = -1
            self.app.action_play_selected()
        else:
            self._last_click_time = now
            self._last_click_y = y


WATCH_SMTHN_THEME = Theme(
    name="ltm_xx",
    primary="#1155ee",
    secondary="#0d47a1",
    warning="#ffa62b",
    error="#ba3c5b",
    success="#4EBF71",
    accent="#1155ee",
    foreground="#e0e0e0",
    background="#000000",
    surface="#000000",
    panel="#0a0a0a",
    dark=True,
)


class WatchSmthnApp(App):
    """Main application for watch somethin."""

    TITLE = "watch somethin"
    SUB_TITLE = "pick somethin to watch"
    THEME = "ltm_xx"

    CSS = """
    Screen {
        layout: horizontal;
        background: #000000;
    }
    #sidebar {
        width: 25;
        min-width: 18;
        background: #000000;
        border: none;
        layout: vertical;
    }
    #sources-panel {
        height: auto;
        max-height: 45%;
        margin: 0 1 0 1;
    }
    #categories-panel {
        height: 1fr;
        margin: 0 1 0 1;
    }
    .panel-edge {
        width: 100%;
        height: 1;
        color: $primary;
        background: #000000;
    }
    .panel-body {
        border-left: round $primary;
        border-right: round $primary;
        background: #000000;
        height: 1fr;
    }
    #sources-panel .panel-body {
        height: auto;
    }
    .panel-row {
        border-left: round $primary;
        border-right: round $primary;
        height: auto;
        background: #000000;
    }
    #add-source-btn {
        width: 100%;
        height: auto;
        min-height: 1;
        background: #000000;
        color: $text-muted;
        text-style: italic;
        border: none;
        text-align: left;
        content-align: left middle;
        padding: 0 0;
    }
    #add-source-btn:focus {
        background: #001d5e;
        color: $primary;
        text-style: italic;
    }
    .sidebar-list {
        height: auto;
        max-height: 100%;
        background: #000000;
    }
    .sidebar-list:focus {
        background: #000000;
        background-tint: #000000 0%;
    }
    .sidebar-list ListItem {
        padding: 0 1;
        background: #000000;
        color: $text-muted;
        width: 100%;
    }
    .sidebar-list ListItem.-highlight {
        color: $primary;
        background: #001d5e;
    }
    .sidebar-list ListItem.-active {
        color: white;
        background: $primary;
    }
    .sidebar-list ListItem.-source-item {
        color: $text-muted;
        text-style: italic;
        background: #000000;
    }
    .sidebar-list ListItem.-highlight.-source-item {
        color: $primary;
        background: #001d5e;
        text-style: italic;
    }
    .sidebar-list ListItem.-active.-source-item {
        color: white;
        background: $primary;
        text-style: italic;
    }
    .sidebar-list ListItem.-category-item {
        color: $text-muted;
        background: #000000;
    }
    .sidebar-list ListItem.-highlight.-category-item {
        color: $primary;
        background: #001d5e;
    }
    .sidebar-list ListItem.-active.-category-item {
        color: white;
        background: $primary;
    }
    #main {
        width: 1fr;
        background: #000000;
        border: round $primary;
    }
    #search-bar {
        dock: top;
        height: 3;
        padding: 0 1;
        background: #000000;
        border: round $primary;
    }
    #channel-table {
        height: 1fr;
        background: #000000;
    }
    #channel-table:focus {
        background: #000000;
        background-tint: #000000 0%;
    }
    #channel-table .datatable--cursor {
        background-tint: #000000 0%;
    }
    #channel-table .datatable--fixed-cursor {
        background-tint: #000000 0%;
    }
    #bottom-bar {
        dock: bottom;
        width: 100%;
        height: 4;
        layout: vertical;
        overflow: hidden;
        background: #0a0a0a;
    }
    #bottom-bar Footer {
        dock: none;
        width: 100%;
        height: 1;
    }
    #status-bar {
        width: 100%;
        height: 3;
        padding: 0 1;
        background: #0a0a0a;
        color: $text-muted;
        border: round $primary;
        content-align: left middle;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("escape", "clear_search", "Clear", show=True),
        Binding("slash", "focus_search", "Search", show=True),
        Binding("enter", "play_selected", "Play", show=True),
        Binding("p", "play_with_select", "Player", show=True),
        Binding("f", "toggle_favorite", "Fav", show=True),
        Binding("ctrl+comma", "edit_config", "Config", show=True),
        Binding("ctrl+r", "reload_config", "Reload", show=True),
        Binding("left", "focus_sidebar", "Categories", show=True, priority=True),
        Binding("right", "focus_table", "Channels", show=True, priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.all_channels: list[Channel] = []
        self.filtered_channels: list[Channel] = []
        self.available_players: list[Player] = []
        self.categories: list[str] = []
        self.sidebar_items: list[dict] = []
        self._source_items: list[dict] = []
        self._category_items: list[dict] = []
        self._sort: Optional[int] = None
        self._sort_desc: bool = False
        self.sources: list[dict[str, Any]] = []
        self.twitch_channels: list[Channel] = []
        self.current_category: str = "All"
        self.current_source_label: str = "iptv"
        self.current_source_idx: int = 0
        self.current_search: str = ""
        self.favorite_urls: set[str] = load_favorites()

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="sidebar"):
                with Vertical(id="sources-panel"):
                    yield Static("", classes="panel-edge", id="sources-top")
                    with Vertical(classes="panel-body"):
                        yield ListView(id="source-list", classes="sidebar-list")
                    yield Static("", classes="panel-edge", id="sidebar-divider")
                    with Vertical(classes="panel-row"):
                        yield Button("+ Add Source", id="add-source-btn")
                    yield Static("", classes="panel-edge", id="sources-bottom")
                with Vertical(id="categories-panel"):
                    yield Static("", classes="panel-edge", id="categories-top")
                    with Vertical(classes="panel-body"):
                        yield ListView(id="category-list", classes="sidebar-list")
                    yield Static("", classes="panel-edge", id="categories-bottom")
            with Vertical(id="main"):
                yield Input(placeholder="Search... (country:PH, group:news, lang:english)", id="search-bar")
                yield PlayableDataTable(id="channel-table")
        with Vertical(id="bottom-bar"):
            yield Footer()
            yield Label(id="status-bar")

    def on_mount(self) -> None:
        self.register_theme(WATCH_SMTHN_THEME)
        self.theme = "ltm_xx"
        self._load_data()
        self.call_later(self._build_sidebar)
        self._build_table()
        self._update_status()
        self.query_one("#channel-table", DataTable).focus()
        self.set_timer(0.1, self._highlight_active_category)
        self.call_after_refresh(self._update_sidebar_geometry)

    def on_resize(self, event: Resize) -> None:
        self._update_sidebar_geometry()

    @staticmethod
    def _edge_top(title: str, width: int) -> str:
        label = f"─ {title} "
        pad = width - 2 - len(label)
        if pad < 0:
            label = label[: max(1, width - 3)]
            pad = max(0, width - 2 - len(label))
        return f"╭{label}{'─' * pad}╮"

    @staticmethod
    def _edge_bottom(width: int) -> str:
        return f"╰{'─' * max(0, width - 2)}╯"

    @staticmethod
    def _edge_divider(width: int) -> str:
        return f"├{'─' * max(0, width - 2)}┤"

    def _update_sidebar_geometry(self) -> None:
        try:
            sidebar = self.query_one("#sidebar")
            src = self.query_one("#sources-panel")
            cat = self.query_one("#categories-panel")
            src_top = self.query_one("#sources-top", Static)
            src_div = self.query_one("#sidebar-divider", Static)
            src_bot = self.query_one("#sources-bottom", Static)
            cat_top = self.query_one("#categories-top", Static)
            cat_bot = self.query_one("#categories-bottom", Static)
            src_body = self.query_one("#sources-panel .panel-body")
        except NoMatches:
            return
        sw = src.region.width
        cw = cat.region.width
        if sw > 2:
            src_top.update(self._edge_top("Sources", sw))
            src_div.update(self._edge_divider(sw))
            src_bot.update(self._edge_bottom(sw))
        if cw > 2:
            cat_top.update(self._edge_top("Categories", cw))
            cat_bot.update(self._edge_bottom(cw))
        sidebar_h = sidebar.region.height
        if sidebar_h > 0:
            src_body.styles.max_height = max(1, int(sidebar_h * 0.45) - 4)

    def _load_data(self) -> None:
        config = load_config()

        custom_players = get_custom_players(config)
        all_players = DEFAULT_PLAYERS + custom_players
        self.available_players = find_available_players(all_players)

        self.sources = load_sources(config)
        if not self.sources:
            self.sources = [{"name": "iptv", "type": "tv", "urls": ["https://iptv-org.github.io/iptv/index.m3u"], "categories": True}]

        self.twitch_channels = load_streamers_from_sources(self.sources)
        for ch in self.twitch_channels:
            ch.favorite = ch.url in self.favorite_urls

        self._load_source(0)

    def _load_source(self, idx: int) -> None:
        if idx < 0 or idx >= len(self.sources):
            return
        self.current_source_idx = idx
        source = self.sources[idx]
        source_type = source.get("type", "tv")
        source_name = source.get("name", "unknown")

        if source_type == "st":
            platform_lower = source_name.lower()
            self.all_channels = [ch for ch in self.twitch_channels if ch.extra.get("platform", "twitch").lower() == platform_lower]
            self.filtered_channels = self._order_channels(list(self.all_channels))
            self.current_category = "All"
            self._mark_favorites()
            self.call_later(self._build_sidebar)
            self._populate_table()
            self._update_status()
            return

        urls = source.get("urls", [])
        if not urls:
            self.all_channels = []
            self.filtered_channels = []
            self.call_later(self._build_sidebar)
            self._populate_table()
            self._update_status()
            return

        self.notify(f"Loading {source_name}...", severity="information")
        self._do_load_source(source)

    def _load_source_group(self, indices: list[int]) -> None:
        if not indices:
            return
        idx = indices[0]
        self._load_source(idx)

    def _mark_favorites(self) -> None:
        for ch in self.all_channels:
            ch.favorite = ch.url in self.favorite_urls

    @staticmethod
    def _name_from_url(url: str) -> str:
        segment = url.split("/")[-1].split("?")[0]
        for ext in (".m3u8", ".m3u", ".mp4", ".ts"):
            if segment.endswith(ext):
                segment = segment[: -len(ext)]
                break
        return segment.replace("_", " ").replace("-", " ").strip().title() or "Channel"

    @work(exclusive=True, group="playlist-loader", thread=True)
    def _do_load_source(self, source: dict[str, Any]) -> None:
        all_channels: list[Channel] = []
        source_name = source.get("name", "unknown")
        source_type = source.get("type", "tv")
        entries = source.get("entries")
        if entries is None:
            entries = [{"url": u, "meta": EntryMeta()} for u in source.get("urls", [])]

        def direct_channel(url: str, meta: EntryMeta) -> Channel:
            row_name = meta.title or self._name_from_url(url)
            group = meta.group or ("" if row_name == source_name else source_name)
            return Channel(
                name=row_name,
                url=url,
                group=group,
                country=meta.country or "",
                language="",
                logo="",
                tvg_id="",
                tvg_name="",
                extra={"source": source_name, "direct": True},
            )

        for entry in entries:
            url = entry["url"]
            meta = entry.get("meta") or EntryMeta()
            try:
                playlist = load_playlist_auto(url, name=source_name, meta=meta)
                if playlist.channels:
                    all_channels.extend(playlist.channels)
                elif source_type == "tv":
                    all_channels.append(direct_channel(url, meta))
            except Exception:
                if source_type == "tv":
                    all_channels.append(direct_channel(url, meta))
        self.all_channels = all_channels
        self.call_from_thread(self._mark_favorites)
        self.filtered_channels = self._order_channels(list(self.all_channels))
        self.current_category = "All"
        self.call_from_thread(self._build_sidebar)
        self.call_from_thread(self._populate_table)
        self.call_from_thread(self._update_status)
        self.call_from_thread(lambda: self.set_timer(0.1, self._highlight_active_category))

    async def _build_sidebar(self) -> None:
        source_lv = self.query_one("#source-list", ListView)
        cat_lv = self.query_one("#category-list", ListView)
        self.sidebar_items = []
        source_items: list[dict] = []
        category_items: list[dict] = []
        source_rows: list[ListItem] = []
        category_rows: list[ListItem] = []

        if self.sources:
            for i, source in enumerate(self.sources):
                label = source.get("name", f"source {i}")
                source_rows.append(ListItem(Label(label), classes="-source-item"))
                item = {"type": "source_group", "indices": [i], "label": label}
                source_items.append(item)
                self.sidebar_items.append(item)

        source_has_categories = True
        if 0 <= self.current_source_idx < len(self.sources):
            source_has_categories = self.sources[self.current_source_idx].get("categories", True)

        if source_has_categories:
            pairs: list[tuple[ListItem, dict]] = []
            pool: list[tuple[str, ListItem, dict]] = []
            has_favorites = any(ch.favorite for ch in self.all_channels)
            if has_favorites:
                pairs.append((
                    ListItem(Label("[#ffa62b]★[/] Favorites"), classes="-category-item"),
                    {"type": "category", "name": "★ Favorites"},
                ))
            pairs.append((
                ListItem(Label("All"), classes="-category-item"),
                {"type": "category", "name": "All"},
            ))
            seen: set[str] = set()
            for ch in self.all_channels:
                if ch.group and ch.group not in seen:
                    seen.add(ch.group)
                    pool.append((
                        ch.group,
                        ListItem(Label(ch.group), classes="-category-item"),
                        {"type": "category", "name": ch.group},
                    ))
            for ct in ContentType:
                matches = [c for c in self.all_channels if c.content_type == ct]
                if matches and ct.value not in seen:
                    seen.add(ct.value)
                    pool.append((
                        ct.value,
                        ListItem(Label(ct.value), classes="-category-item"),
                        {"type": "category", "name": ct.value},
                    ))
            # Favorites/All are semantic rather than alphabetical, so they stay
            # pinned; everything else is one A-Z block regardless of whether it
            # came from a file group-title or a ContentType. The three lists
            # below are index-parallel and must be appended together.
            pool.sort(key=lambda p: p[0].casefold())
            pairs.extend((row, item) for _, row, item in pool)
            for row, item in pairs:
                category_rows.append(row)
                category_items.append(item)
                self.sidebar_items.append(item)

        self._source_items = source_items
        self._category_items = category_items
        self.categories = [i["name"] for i in category_items]

        await source_lv.clear()
        await cat_lv.clear()
        if source_rows:
            await source_lv.extend(source_rows)
        if category_rows:
            await cat_lv.extend(category_rows)
        self._highlight_active_category()

    def _header_labels(self) -> tuple[str, ...]:
        if self._sort is None:
            return _HEADER_NAMES
        mark = "▼" if self._sort_desc else "▲"
        return tuple(
            name + (f" {mark}" if i == self._sort else "")
            for i, name in enumerate(_HEADER_NAMES)
        )

    def _rebuild_headers(self) -> None:
        table = self.query_one("#channel-table", DataTable)
        table.clear(columns=True)
        table.add_columns(*self._header_labels())

    def _build_table(self) -> None:
        self._rebuild_headers()
        self._populate_table()

    @on(DataTable.HeaderSelected)
    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        idx = event.column_index
        if idx not in (0, 1, 2):
            return
        if self._sort != idx:
            self._sort, self._sort_desc = idx, False
        elif not self._sort_desc:
            self._sort_desc = True
        else:
            self._sort, self._sort_desc = None, False
        self._rebuild_headers()
        self._filter_channels()

    def _highlight_active_category(self) -> None:
        source_lv = self.query_one("#source-list", ListView)
        cat_lv = self.query_one("#category-list", ListView)
        for i, child in enumerate(source_lv.children):
            if isinstance(child, ListItem) and i < len(self._source_items):
                item = self._source_items[i]
                if item["type"] == "source_group":
                    child.set_class(item["label"] == self.current_source_label, "-active")
                else:
                    child.remove_class("-active")
        for i, child in enumerate(cat_lv.children):
            if isinstance(child, ListItem) and i < len(self._category_items):
                item = self._category_items[i]
                if item["type"] == "category":
                    child.set_class(item["name"] == self.current_category, "-active")
                else:
                    child.remove_class("-active")

    def _populate_table(self) -> None:
        table = self.query_one("#channel-table", DataTable)
        saved_row = table.cursor_row if table.cursor_row is not None and table.row_count > 0 else 0
        table.clear()
        for ch in self.filtered_channels:
            name = f"[#ffa62b]★[/] {ch.name}" if ch.favorite else ch.name
            table.add_row(
                name,
                ch.group or "-",
                ch.country or "-",
            )
        if self.filtered_channels:
            table.cursor_type = "row"
            table.move_cursor(row=min(saved_row, len(self.filtered_channels) - 1))

    def _order_channels(self, channels: list[Channel]) -> list[Channel]:
        """Default A-Z by name; a header sort overrides it.

        Sorts ``filtered_channels``, never ``DataTable.sort`` -- the table row
        index is what `_get_selected_channel` resolves, so the widget and the
        list have to move together. `all_channels` is deliberately left in
        file order so filtering and favorites stay independent of view order.

        Python's sort is stable in both directions, so equal keys keep their
        incoming (file) order instead of shuffling.
        """
        if self._sort is None:
            return sorted(channels, key=lambda c: c.name.casefold())
        field = (lambda c: c.name, lambda c: c.group, lambda c: c.country)[self._sort]
        return sorted(channels, key=lambda c: field(c).casefold(), reverse=self._sort_desc)

    def _filter_channels(self) -> None:
        channels = list(self.all_channels)
        if self.current_category == "★ Favorites":
            channels = [c for c in channels if c.favorite]
        elif self.current_category != "All":
            channels = [
                c for c in channels
                if c.group == self.current_category or c.content_type.value == self.current_category
            ]
        if self.current_search:
            raw = self.current_search.strip()
            param = _SEARCH_PARAM_RE.match(raw)
            if param:
                key, value = param.group(1).lower(), param.group(2).lower()
                if key == "country":
                    channels = [c for c in channels if c.country.lower() == value]
                elif key == "lang":
                    channels = [c for c in channels if value in c.language.lower()]
                else:
                    channels = [c for c in channels if value in c.group.lower()]
            else:
                q = raw.lower()
                channels = [
                    c for c in channels
                    if q in c.name.lower()
                    or q in c.group.lower()
                    or q in c.content_type.value.lower()
                    or q in c.country.lower()
                    or q in c.language.lower()
                ]
        self.filtered_channels = self._order_channels(channels)
        self._populate_table()
        self._update_status()

    def _update_status(self) -> None:
        total = len(self.all_channels)
        showing = len(self.filtered_channels)
        pl_name = ""
        if self.sources and 0 <= self.current_source_idx < len(self.sources):
            pl_name = self.sources[self.current_source_idx].get("name", "")
        status = f" {showing}/{total} channels"
        if pl_name:
            status += f" | {pl_name}"
        if self.current_category != "All":
            status += f" | {self.current_category}"
        if self.current_search:
            status += f" | \"{self.current_search}\""
        self.query_one("#status-bar", Label).update(status)

    @on(Input.Changed, "#search-bar")
    def on_search_changed(self, event: Input.Changed) -> None:
        self.current_search = event.value
        self._filter_channels()

    @on(Input.Submitted, "#search-bar")
    def on_search_submitted(self, event: Input.Submitted) -> None:
        self.query_one("#channel-table", DataTable).focus()

    @on(ListView.Selected, "#source-list")
    def on_source_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if idx is None or idx < 0 or idx >= len(self._source_items):
            return
        item = self._source_items[idx]
        if item["type"] == "source_group":
            self.current_source_label = item["label"]
            self._load_source_group(item["indices"])
        self._highlight_active_category()

    @on(Button.Pressed, "#add-source-btn")
    def on_add_source_pressed(self) -> None:
        self.push_screen(AddSourceScreen(), self._on_add_source)

    @on(ListView.Selected, "#category-list")
    def on_category_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if idx is None or idx < 0 or idx >= len(self._category_items):
            return
        item = self._category_items[idx]
        if item["type"] == "category":
            self.current_category = item["name"]
            self._filter_channels()
        self._highlight_active_category()

    def _on_add_source(self, entry: Optional[dict[str, Any]]) -> None:
        if not entry:
            return
        config = load_config()
        if entry.get("type") == "tv":
            save_custom_source_to_config(config, entry)
            self.notify(f"Added source: {entry['name']}", severity="information")
        else:
            platform = entry["platform"].title()
            handles = entry["handles"]
            for handle in handles:
                save_handle_to_config(config, platform, handle)
            count = len(handles)
            self.notify(f"Added {count} handle{'s' if count > 1 else ''} to {platform}", severity="information")
        config = load_config()
        self.sources = load_sources(config)
        self.twitch_channels = load_streamers_from_sources(self.sources)

        labels = [s.get("name", "") for s in self.sources]
        if self.current_source_label in labels:
            self.current_source_idx = labels.index(self.current_source_label)
            source = self.sources[self.current_source_idx]
            if source.get("type", "tv") == "st":
                # streamer handles may have changed, so rebuild this source's channels
                self._load_source(self.current_source_idx)
                return
            # only a new source was appended; the current source's channels are unchanged
            self.call_later(self._build_sidebar)
            return

        # the source we were viewing no longer exists -- fall back to the first one
        if labels:
            self.current_source_label = labels[0]
            self._load_source(0)
            return

        self.current_source_idx = 0
        self.current_source_label = ""
        self.all_channels = []
        self.filtered_channels = []
        self.current_category = "All"
        self.call_later(self._build_sidebar)
        self._populate_table()
        self._update_status()

    def _get_selected_channel(self) -> Optional[Channel]:
        table = self.query_one("#channel-table", DataTable)
        if table.cursor_row is not None and 0 <= table.cursor_row < len(self.filtered_channels):
            return self.filtered_channels[table.cursor_row]
        return None

    def action_focus_search(self) -> None:
        self.query_one("#search-bar", Input).focus()

    def _focus_sidebar_at(self, item_type: str, name: str | None = None) -> None:
        for items, lv_id in [(self._source_items, "#source-list"), (self._category_items, "#category-list")]:
            if name:
                for i, item in enumerate(items):
                    if item["type"] == item_type and item.get("name", item.get("label")) == name:
                        lv = self.query_one(lv_id, ListView)
                        lv.index = i
                        lv.focus()
                        return
            for i, item in enumerate(items):
                if item["type"] == item_type:
                    lv = self.query_one(lv_id, ListView)
                    lv.index = i
                    lv.focus()
                    return
        if self._category_items:
            self.query_one("#category-list", ListView).focus()
        elif self._source_items:
            self.query_one("#source-list", ListView).focus()

    def _focus_table_first(self) -> None:
        table = self.query_one("#channel-table", DataTable)
        if table.row_count > 0:
            table.move_cursor(row=0)
        table.focus()

    def on_key(self, event: Key) -> None:
        focused = self.focused
        search_focused = focused and focused.id == "search-bar"
        sidebar_focused = focused and focused.id in ("category-list", "source-list", "add-source-btn")

        if event.key == "enter" and not search_focused and not sidebar_focused:
            channel = self._get_selected_channel()
            if channel:
                event.stop()
                self.action_play_selected()

    def _has_categories(self) -> bool:
        return len(self._category_items) > 0

    def action_focus_sidebar(self) -> None:
        if self.focused and self.focused.id == "search-bar":
            return
        if self.focused and self.focused.id == "channel-table":
            if self._has_categories():
                self._focus_sidebar_at("category", self.current_category)
            else:
                self._focus_sidebar_at("source_group", self.current_source_label)
            return
        if self.focused and self.focused.id == "category-list":
            if self._has_categories():
                self._focus_sidebar_at("source_group", self.current_source_label)
                return
        if self.focused and self.focused.id == "source-list":
            if self._has_categories():
                self._focus_sidebar_at("category", self.current_category)
                return
        self._focus_sidebar_at("category", self.current_category)

    def action_focus_table(self) -> None:
        if self.focused and self.focused.id == "search-bar":
            return
        if self.focused and self.focused.id == "source-list":
            if self._has_categories():
                self._focus_sidebar_at("category")
                return
        self._focus_table_first()

    def action_clear_search(self) -> None:
        inp = self.query_one("#search-bar", Input)
        inp.value = ""
        self.current_search = ""
        self._filter_channels()
        self.query_one("#channel-table", DataTable).focus()

    def action_play_selected(self) -> None:
        channel = self._get_selected_channel()
        if not channel:
            return
        default = next((p for p in self.available_players if p.is_default), None)
        if default:
            self._launch(channel, default)
        elif self.available_players:
            self._show_player_select(channel)

    def action_play_with_select(self) -> None:
        channel = self._get_selected_channel()
        if channel:
            self._show_player_select(channel)

    def action_toggle_favorite(self) -> None:
        channel = self._get_selected_channel()
        if not channel:
            return
        is_now_fav = toggle_favorite(self.favorite_urls, channel.url)
        channel.favorite = is_now_fav
        label = "★ Added to" if is_now_fav else "☆ Removed from"
        self.notify(f"{label} favorites: {channel.name}", severity="information")
        self.call_later(self._build_sidebar)
        self._populate_table()

    def action_edit_config(self) -> None:
        from .config import CONFIG_DIRS, BUNDLED_CONFIG
        config_path = _find_config()
        if not config_path:
            config_path = CONFIG_DIRS[0] / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            if BUNDLED_CONFIG.exists():
                config_path.write_text(BUNDLED_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
        try:
            open_in_editor(config_path)
            self.notify(f"Opened {config_path}", severity="information")
        except Exception as e:
            self.notify(f"Failed to open editor: {e}", severity="error")

    def action_reload_config(self) -> None:
        self.favorite_urls = load_favorites()
        config = load_config()
        self.available_players = find_available_players(DEFAULT_PLAYERS + get_custom_players(config))
        self.sources = load_sources(config)
        if not self.sources:
            self.sources = [{"name": "iptv", "type": "tv", "urls": ["https://iptv-org.github.io/iptv/index.m3u"], "categories": True}]
        self.twitch_channels = load_streamers_from_sources(self.sources)
        for ch in self.twitch_channels:
            ch.favorite = ch.url in self.favorite_urls
        self.current_source_idx = min(self.current_source_idx, len(self.sources) - 1)
        self._load_source(self.current_source_idx)
        self.notify("Config reloaded", severity="information")

    def _show_player_select(self, channel: Channel) -> None:
        if not self.available_players:
            self.notify("No players found!", severity="error")
            return
        self.push_screen(PlayerSelectScreen(self.available_players, channel.name), lambda p: self._on_player_picked(channel, p))

    def _on_player_picked(self, channel: Channel, player: Optional[Player]) -> None:
        if player:
            self._launch(channel, player)

    def _launch(self, channel: Channel, player: Player) -> None:
        if channel.extra.get("streamlink"):
            quality = channel.extra.get("quality", "best")
            url = channel.url
            try:
                spawn(build_streamlink_command(url, quality))
                platform = channel.extra.get("platform", "streamlink")
                self.notify(f"Playing {channel.name} via {platform}", severity="information")
            except FileNotFoundError:
                self.notify("streamlink not found — install it first", severity="error")
            except Exception as e:
                self.notify(f"Failed to launch streamlink: {e}", severity="error")
            return
        proc = launch_player(player, channel.url)
        if proc:
            self.notify(f"Playing {channel.name} in {player.name}", severity="information")
        else:
            self.notify(f"Failed to launch {player.name}", severity="error")
