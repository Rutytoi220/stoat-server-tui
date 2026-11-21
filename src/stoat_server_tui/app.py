"""Main Textual TUI application for Stoat Server (ss-tui)."""

from __future__ import annotations

import argparse
import re
from typing import Any

from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import DataTable, Label, ListItem, ListView, RichLog, Static
from rich.text import Text

from .backend import StoatBackend
from .modals import ConfirmModal, HelpModal, InputModal

TABS: list[tuple[str, str, str]] = [
    ("dashboard", "1", "◈  Dashboard"),
    ("services", "2", "⊞  Services"),
    ("users", "3", "◉  Users"),
    ("config", "4", "⚙  Limits & Config"),
    ("funnel", "5", "⇄  Tailscale Funnel"),
    ("logs", "6", "≡  Logs"),
]

DEFAULT_LOG_SERVICES = [
    "api",
    "autumn",
    "web",
    "caddy",
    "events",
    "database",
    "minio",
    "january",
    "livekit",
    "gifbox",
]


def fmt_bytes(val: Any) -> str:
    try:
        n = int(val)
    except (TypeError, ValueError):
        return str(val)
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f} GB ({n:,})"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f} MB ({n:,})"
    if n >= 1_000:
        return f"{n / 1_000:.2f} KB ({n:,})"
    return f"{n} B"


def parse_size_input(raw: str) -> int:
    s = raw.strip().replace("_", "").replace(",", "").upper()
    m = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(B|KB|MB|GB|TB)?", s)
    if not m:
        raise ValueError(f"Invalid size/number: {raw!r} (try e.g. 10GB, 50MB, or 20000000)")
    num = float(m.group(1))
    unit = m.group(2) or "B"
    mult = {
        "B": 1,
        "KB": 1_000,
        "MB": 1_000_000,
        "GB": 1_000_000_000,
        "TB": 1_000_000_000_000,
    }[unit]
    return int(num * mult)


class StoatServerApp(App):
    """Keyboard-first (HJKL) Stoat Server Management TUI (ss-tui)."""

    TITLE = "Stoat Server TUI"
    CSS = """
    Screen {
        background: ansi_default;
        color: #eef0f7;
    }

    #topbar {
        height: 1;
        background: #1b2030;
        color: #88c0d0;
        padding: 0 2;
        content-align: left middle;
    }

    #body {
        height: 1fr;
    }

    #sidebar {
        width: 27;
        border-right: solid #2e3440;
        background: ansi_default;
        padding: 1 0;
    }

    #sidebar ListItem {
        padding: 0 2;
        height: 2;
        content-align: left middle;
    }

    #sidebar ListItem.--highlight {
        background: #2e3440;
        color: #88c0d0;
        text-style: bold;
    }

    #main {
        width: 1fr;
        padding: 1 2;
        background: ansi_default;
    }

    .pane {
        height: 1fr;
        display: none;
    }

    .pane.active {
        display: block;
    }

    .pane-title {
        text-style: bold;
        color: #88c0d0;
        margin-bottom: 1;
    }

    .hint-bar {
        color: #7c8599;
        height: auto;
        margin-bottom: 1;
    }

    .card {
        border: round #3b4252;
        padding: 1 2;
        margin-bottom: 1;
        height: auto;
    }

    DataTable {
        height: 1fr;
        background: ansi_default;
    }

    RichLog {
        height: 1fr;
        border: round #3b4252;
        padding: 0 1;
        background: ansi_default;
    }

    #statusbar {
        height: 1;
        background: #1b2030;
        color: #d8dee9;
        padding: 0 2;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
        Binding("question_mark", "show_help", "Help"),
        Binding("r", "refresh_current", "Refresh"),
        Binding("1", "tab_idx(0)", "Dashboard", show=False),
        Binding("2", "tab_idx(1)", "Services", show=False),
        Binding("3", "tab_idx(2)", "Users", show=False),
        Binding("4", "tab_idx(3)", "Limits", show=False),
        Binding("5", "tab_idx(4)", "Funnel", show=False),
        Binding("6", "tab_idx(5)", "Logs", show=False),
        Binding("h", "focus_sidebar", "Sidebar", show=False),
        Binding("l", "focus_main", "Content", show=False),
    ]

    def __init__(self, backend: StoatBackend) -> None:
        super().__init__()
        self.backend = backend
        self.active_tab = "dashboard"
        self._services: list[dict[str, Any]] = []
        self._users: list[dict[str, Any]] = []
        self._config_rows: list[tuple[str, str, Any, str]] = []
        self._log_services: list[str] = list(DEFAULT_LOG_SERVICES)
        self._log_svc_idx = 0
        self._hide_otel = True

    def compose(self) -> ComposeResult:
        yield Static(
            f"◈ STOAT SERVER TUI (ss-tui)   │   target: {self.backend.target_label}   │   dir: {self.backend.stoat_dir}   │   [bold]?[/] Help  [bold]q[/] Quit",
            id="topbar",
        )
        with Horizontal(id="body"):
            items = [
                ListItem(Label(f"[dim]{key}[/] {label}"), id=f"nav-{tab_id}")
                for tab_id, key, label in TABS
            ]
            yield ListView(*items, id="sidebar")
            with Vertical(id="main"):
                # 1. Dashboard
                with VerticalScroll(id="pane-dashboard", classes="pane active"):
                    yield Static("◈ Dashboard", classes="pane-title")
                    yield Static(
                        "[dim]Keys:[/] [bold]r[/] Refresh   [bold]R[/] Restart All   [bold]i[/] Re-run inject.js   [bold]m[/] Auto-Mesh Friends",
                        classes="hint-bar",
                    )
                    yield Static("Loading server status…", id="dash-summary", classes="card")
                    yield Static("", id="dash-endpoints", classes="card")
                    yield Static("", id="dash-db", classes="card")

                # 2. Services
                with Vertical(id="pane-services", classes="pane"):
                    yield Static("⊞ Docker Services", classes="pane-title")
                    yield Static(
                        "[dim]Keys:[/] [bold]j/k[/] Move   [bold]Enter[/] View Logs   [bold]s[/] Start   [bold]x[/] Stop   [bold]R[/] Restart   [bold]F[/] Force-Recreate",
                        classes="hint-bar",
                    )
                    yield DataTable(id="tbl-services", cursor_type="row")

                # 3. Users
                with Vertical(id="pane-users", classes="pane"):
                    yield Static("◉ Users & Accounts", classes="pane-title")
                    yield Static(
                        "[dim]Keys:[/] [bold]p[/] Reset Password   [bold]u[/] Unlock/Clear Timeout   [bold]K[/] Revoke Sessions   [bold]d[/] Disable/Enable   [bold]D[/] Delete   [bold]m[/] Mesh Friends",
                        classes="hint-bar",
                    )
                    yield DataTable(id="tbl-users", cursor_type="row")

                # 4. Limits & Config
                with Vertical(id="pane-config", classes="pane"):
                    yield Static("⚙ Limits & Configuration (Revolt.toml)", classes="pane-title")
                    yield Static(
                        "[dim]Keys:[/] [bold]Enter / e[/] Edit Selected Limit   [bold]i[/] Re-run inject.js & Restart Caddy   [bold]r[/] Refresh",
                        classes="hint-bar",
                    )
                    yield DataTable(id="tbl-config", cursor_type="row")

                # 5. Tailscale Funnel
                with VerticalScroll(id="pane-funnel", classes="pane"):
                    yield Static("⇄ Tailscale Funnel & Access", classes="pane-title")
                    yield Static("[dim]Keys:[/] [bold]r[/] Refresh", classes="hint-bar")
                    yield Static("Loading Tailscale Funnel status…", id="funnel-box", classes="card")

                # 6. Logs
                with Vertical(id="pane-logs", classes="pane"):
                    yield Static("≡ Container Logs", id="logs-title", classes="pane-title")
                    yield Static(
                        "[dim]Keys:[/] [bold]\\[ / \\][/] Prev/Next Service   [bold]o[/] Toggle OpenTelemetry Filter   [bold]r[/] Reload   [bold]j/k[/] Scroll",
                        classes="hint-bar",
                    )
                    yield RichLog(id="log-view", highlight=False, markup=False, wrap=True)

        yield Static("Ready.", id="statusbar")

    def on_mount(self) -> None:
        # Setup tables
        ts = self.query_one("#tbl-services", DataTable)
        ts.add_columns("Service", "State", "Status", "Image", "Ports")

        tu = self.query_one("#tbl-users", DataTable)
        tu.add_columns("Username", "Email", "Sessions", "Msgs", "Friends", "State", "User ID")

        tc = self.query_one("#tbl-config", DataTable)
        tc.add_columns("Key", "Setting", "Current Value")

        self.query_one("#sidebar", ListView).index = 0
        self.load_overview()

    def set_status(self, msg: str, error: bool = False) -> None:
        bar = self.query_one("#statusbar", Static)
        prefix = ("ERR ", "bold #bf616a") if error else ("● ", "bold #a3be8c")
        bar.update(Text.assemble(prefix, msg))

    # ------------------------------------------------------------------
    # Navigation & Key Handling
    # ------------------------------------------------------------------
    def _switch_tab(self, tab_id: str) -> None:
        self.active_tab = tab_id
        for tid, _, _ in TABS:
            pane = self.query_one(f"#pane-{tid}")
            pane.set_class(tid == tab_id, "active")

        idx = next((i for i, (tid, _, _) in enumerate(TABS) if tid == tab_id), 0)
        lv = self.query_one("#sidebar", ListView)
        if lv.index != idx:
            lv.index = idx

        self.action_refresh_current()

    def action_tab_idx(self, idx: int) -> None:
        if 0 <= idx < len(TABS):
            self._switch_tab(TABS[idx][0])
            self.action_focus_main()

    def action_focus_sidebar(self) -> None:
        self.query_one("#sidebar", ListView).focus()

    def action_focus_main(self) -> None:
        if self.active_tab == "services":
            self.query_one("#tbl-services", DataTable).focus()
        elif self.active_tab == "users":
            self.query_one("#tbl-users", DataTable).focus()
        elif self.active_tab == "config":
            self.query_one("#tbl-config", DataTable).focus()
        elif self.active_tab == "logs":
            self.query_one("#log-view", RichLog).focus()
        else:
            self.query_one(f"#pane-{self.active_tab}").focus()

    def action_show_help(self) -> None:
        self.push_screen(HelpModal())

    def action_refresh_current(self) -> None:
        if self.active_tab in ("dashboard", "services", "funnel"):
            self.load_overview()
        elif self.active_tab == "users":
            self.load_users()
        elif self.active_tab == "config":
            self.load_config()
        elif self.active_tab == "logs":
            self.load_logs()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id == "sidebar" and event.item and event.item.id:
            tab_id = event.item.id.removeprefix("nav-")
            if tab_id != self.active_tab:
                self._switch_tab(tab_id)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "sidebar" and event.item and event.item.id:
            tab_id = event.item.id.removeprefix("nav-")
            self._switch_tab(tab_id)
            self.action_focus_main()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "tbl-services":
            svc = self._selected_service()
            if svc:
                name = svc.get("Service", "")
                if name in self._log_services:
                    self._log_svc_idx = self._log_services.index(name)
                else:
                    self._log_services.insert(0, name)
                    self._log_svc_idx = 0
                self._switch_tab("logs")
                self.action_focus_main()
        elif event.data_table.id == "tbl-config":
            self._prompt_edit_limit()

    def on_key(self, event: events.Key) -> None:
        # Don't hijack keys when a modal is open
        if len(self.screen_stack) > 1:
            return

        key = event.key
        focused = self.focused

        # Vim j/k movement
        if key == "j":
            if isinstance(focused, DataTable):
                focused.action_cursor_down()
                event.stop()
                return
            if isinstance(focused, ListView):
                focused.action_cursor_down()
                event.stop()
                return
            if isinstance(focused, (RichLog, VerticalScroll)):
                focused.scroll_down(animate=False)
                event.stop()
                return
        elif key == "k" and self.active_tab != "users":
            if isinstance(focused, DataTable):
                focused.action_cursor_up()
                event.stop()
                return
            if isinstance(focused, ListView):
                focused.action_cursor_up()
                event.stop()
                return
            if isinstance(focused, (RichLog, VerticalScroll)):
                focused.scroll_up(animate=False)
                event.stop()
                return
        elif key == "k" and self.active_tab == "users":
            # In users tab, if sidebar is focused, k moves up; if table is focused, k moves up and Shift+K revokes sessions?
            # Keep k = vim up everywhere for consistency, and use 'K' or 's' for revoke sessions!
            if isinstance(focused, DataTable):
                focused.action_cursor_up()
                event.stop()
                return
            if isinstance(focused, ListView):
                focused.action_cursor_up()
                event.stop()
                return

        # Context-specific action keys
        if self.active_tab == "dashboard":
            if key == "R":
                self._confirm_restart_all()
                event.stop()
            elif key == "i":
                self._run_inject()
                event.stop()
            elif key == "m":
                self._run_mesh_friends()
                event.stop()

        elif self.active_tab == "services":
            if key == "s":
                self._run_selected_service_action("start")
                event.stop()
            elif key == "x":
                self._run_selected_service_action("stop")
                event.stop()
            elif key == "R":
                self._run_selected_service_action("restart")
                event.stop()
            elif key == "F":
                self._run_selected_service_action("recreate")
                event.stop()

        elif self.active_tab == "users":
            if key == "p":
                self._prompt_reset_password()
                event.stop()
            elif key == "u":
                self._run_unlock_user()
                event.stop()
            elif key == "K":
                self._confirm_revoke_sessions()
                event.stop()
            elif key == "d":
                self._run_toggle_disable()
                event.stop()
            elif key == "D":
                self._confirm_delete_user()
                event.stop()
            elif key == "m":
                self._run_mesh_friends()
                event.stop()

        elif self.active_tab == "config":
            if key == "e":
                self._prompt_edit_limit()
                event.stop()
            elif key == "i":
                self._run_inject()
                event.stop()

        elif self.active_tab == "logs":
            if key == "left_square_bracket":
                self._log_svc_idx = (self._log_svc_idx - 1) % len(self._log_services)
                self.load_logs()
                event.stop()
            elif key == "right_square_bracket":
                self._log_svc_idx = (self._log_svc_idx + 1) % len(self._log_services)
                self.load_logs()
                event.stop()
            elif key == "o":
                self._hide_otel = not self._hide_otel
                self.load_logs()
                event.stop()

    # ------------------------------------------------------------------
    # Data Loaders (Background Workers)
    # ------------------------------------------------------------------
    @work(exclusive=True, thread=True, group="overview")
    def load_overview(self) -> None:
        self.call_from_thread(self.set_status, f"Refreshing overview from {self.backend.target_label}…")
        try:
            data = self.backend.fetch_overview()
        except Exception as exc:
            self.call_from_thread(self.set_status, str(exc), True)
            return
        self.call_from_thread(self._apply_overview, data)

    def _apply_overview(self, data: dict[str, Any]) -> None:
        services = data.get("services", [])
        self._services = services
        if services:
            self._log_services = [s.get("Service", "") for s in services if s.get("Service")]
            if self._log_svc_idx >= len(self._log_services):
                self._log_svc_idx = 0

        running = sum(1 for s in services if str(s.get("State", "")).lower() == "running")
        api = data.get("api", {})
        stoat_ver = api.get("stoat", api.get("revolt", "offline"))
        api_ok = "[bold #a3be8c]ONLINE[/]" if api else "[bold #bf616a]OFFLINE[/]"

        self.query_one("#dash-summary", Static).update(
            f"[bold #88c0d0]Stack Health[/]\n"
            f"  API Status : {api_ok}   (Stoat v{stoat_ver})\n"
            f"  Containers : [bold]{running} / {len(services)}[/] running\n"
            f"  Disk Usage : {data.get('disk', '—')}\n"
            f"  Memory     : {data.get('mem', '—')}"
        )

        feats = api.get("features", {})
        limits = feats.get("limits", {}).get("default", {}).get("file_upload_size_limits", {})
        self.query_one("#dash-endpoints", Static).update(
            f"[bold #88c0d0]Endpoints & Limits[/]\n"
            f"  App URL    : {api.get('app', '—')}\n"
            f"  WebSocket  : {api.get('ws', '—')}\n"
            f"  Autumn     : {feats.get('autumn', {}).get('url', '—')}\n"
            f"  Max Upload : {fmt_bytes(limits.get('attachments', '—'))}"
        )

        db = data.get("db", {})
        self.query_one("#dash-db", Static).update(
            f"[bold #88c0d0]MongoDB Stats[/]\n"
            f"  Accounts : {db.get('accounts', '—')}   │   Users : {db.get('users', '—')}   │   Active Sessions : {db.get('sessions', '—')}\n"
            f"  Channels : {db.get('channels', '—')}   │   Messages : {db.get('messages', '—')}   │   Servers : {db.get('servers', '—')}"
        )

        self.query_one("#funnel-box", Static).update(
            f"[bold #88c0d0]Tailscale Funnel Status[/]\n\n{data.get('funnel', '—')}"
        )

        # Populate Services DataTable
        ts = self.query_one("#tbl-services", DataTable)
        prev_row = ts.cursor_row
        ts.clear()
        for s in services:
            state = str(s.get("State", ""))
            state_fmt = f"[#a3be8c]{state}[/]" if state == "running" else f"[#bf616a]{state}[/]"
            ts.add_row(
                s.get("Service", ""),
                state_fmt,
                s.get("Status", ""),
                s.get("Image", ""),
                s.get("Ports", ""),
            )
        if services:
            ts.move_cursor(row=min(prev_row, len(services) - 1))

        self.set_status(f"Overview updated ({running}/{len(services)} containers running).")

    @work(exclusive=True, thread=True, group="users")
    def load_users(self) -> None:
        self.call_from_thread(self.set_status, "Loading users from MongoDB…")
        try:
            users = self.backend.fetch_users()
        except Exception as exc:
            self.call_from_thread(self.set_status, str(exc), True)
            return
        self.call_from_thread(self._apply_users, users)

    def _apply_users(self, users: list[dict[str, Any]]) -> None:
        self._users = users
        tu = self.query_one("#tbl-users", DataTable)
        prev_row = tu.cursor_row
        tu.clear()
        for u in users:
            flags = []
            if u.get("disabled"):
                flags.append("[#bf616a]DISABLED[/]")
            if u.get("locked"):
                flags.append("[#ebcb8b]LOCKED[/]")
            state_str = " ".join(flags) if flags else "[#a3be8c]Active[/]"
            uname = u.get("username", "")
            disc = u.get("discriminator", "")
            display = f"{uname}#{disc}" if disc else uname
            tu.add_row(
                display,
                u.get("email", ""),
                str(u.get("sessions", 0)),
                str(u.get("messages", 0)),
                str(u.get("friends", 0)),
                state_str,
                u.get("id", ""),
            )
        if users:
            tu.move_cursor(row=min(prev_row, len(users) - 1))
        self.set_status(f"Loaded {len(users)} account(s). Press [K] to revoke sessions, [p] to reset password.")

    @work(exclusive=True, thread=True, group="config")
    def load_config(self) -> None:
        self.call_from_thread(self.set_status, "Loading Revolt.toml & API limits…")
        try:
            cfg = self.backend.fetch_config()
        except Exception as exc:
            self.call_from_thread(self.set_status, str(exc), True)
            return
        self.call_from_thread(self._apply_config, cfg)

    def _apply_config(self, cfg: dict[str, Any]) -> None:
        rows = cfg.get("rows", [])
        self._config_rows = rows
        tc = self.query_one("#tbl-config", DataTable)
        prev_row = tc.cursor_row
        tc.clear()
        for key, label, val, unit in rows:
            val_fmt = fmt_bytes(val) if unit == "bytes" else f"{val:,} {unit}" if isinstance(val, int) else str(val)
            tc.add_row(key, label, val_fmt)
        if rows:
            tc.move_cursor(row=min(prev_row, len(rows) - 1))
        self.set_status("Config loaded. Press [Enter] or [e] on any row to edit.")

    @work(exclusive=True, thread=True, group="logs")
    def load_logs(self) -> None:
        svc = self._log_services[self._log_svc_idx] if self._log_services else "api"
        self.call_from_thread(self.set_status, f"Fetching logs for {svc}…")
        try:
            text = self.backend.fetch_logs(svc, lines=140, hide_otel=self._hide_otel)
        except Exception as exc:
            self.call_from_thread(self.set_status, str(exc), True)
            return
        self.call_from_thread(self._apply_logs, svc, text)

    def _apply_logs(self, svc: str, text: str) -> None:
        otel_tag = "ON" if self._hide_otel else "OFF"
        self.query_one("#logs-title", Static).update(
            f"≡ Logs: [bold #ebcb8b]{svc}[/]   ({self._log_svc_idx + 1}/{len(self._log_services)})   │   Hide OTel spam: {otel_tag}"
        )
        log = self.query_one("#log-view", RichLog)
        log.clear()
        for line in text.splitlines():
            log.write(line)
        self.set_status(f"Showing last logs for {svc}.")

    # ------------------------------------------------------------------
    # Selection Helpers & Actions
    # ------------------------------------------------------------------
    def _selected_service(self) -> dict[str, Any] | None:
        ts = self.query_one("#tbl-services", DataTable)
        if 0 <= ts.cursor_row < len(self._services):
            return self._services[ts.cursor_row]
        return None

    def _selected_user(self) -> dict[str, Any] | None:
        tu = self.query_one("#tbl-users", DataTable)
        if 0 <= tu.cursor_row < len(self._users):
            return self._users[tu.cursor_row]
        return None

    def _selected_config(self) -> tuple[str, str, Any, str] | None:
        tc = self.query_one("#tbl-config", DataTable)
        if 0 <= tc.cursor_row < len(self._config_rows):
            return self._config_rows[tc.cursor_row]
        return None

    def _confirm_restart_all(self) -> None:
        def _cb(ok: bool) -> None:
            if ok:
                self._do_service_action("", "restart_all")
        self.push_screen(
            ConfirmModal("Restart All Services", "Restart the entire Stoat Docker Compose stack?", "Restart All"),
            _cb,
        )

    def _run_selected_service_action(self, action: str) -> None:
        svc = self._selected_service()
        if not svc:
            return
        name = svc.get("Service", "")
        if action in ("stop", "recreate"):
            self.push_screen(
                ConfirmModal(
                    f"{action.title()} Service",
                    f"Are you sure you want to {action} [bold]{name}[/]?",
                    action.title(),
                ),
                lambda ok: ok and self._do_service_action(name, action),
            )
        else:
            self._do_service_action(name, action)

    @work(thread=True)
    def _do_service_action(self, service: str, action: str) -> None:
        label = service or "all services"
        self.call_from_thread(self.set_status, f"Running {action} on {label}…")
        try:
            self.backend.service_action(service, action)
        except Exception as exc:
            self.call_from_thread(self.set_status, str(exc), True)
            return
        self.call_from_thread(self.set_status, f"Completed {action} on {label}.")
        self.load_overview()

    def _prompt_reset_password(self) -> None:
        user = self._selected_user()
        if not user:
            return
        uname = user.get("username", "")
        email = user.get("email", "")
        uid = user.get("id", "")

        def _cb(val: str | None) -> None:
            if val is None:
                return
            self._do_reset_password(uid, email, uname, val.strip() or None)

        self.push_screen(
            InputModal(
                f"Reset Password — {uname}",
                f"Email: [bold]{email}[/]\nEnter a new password, or leave blank to auto-generate one:",
                placeholder="Leave blank for random password",
            ),
            _cb,
        )

    @work(thread=True)
    def _do_reset_password(self, uid: str, email: str, uname: str, pw: str | None) -> None:
        self.call_from_thread(self.set_status, f"Resetting password for {uname} ({email})…")
        try:
            final_pw = self.backend.reset_password(uid, email, pw)
        except Exception as exc:
            self.call_from_thread(self.set_status, str(exc), True)
            return
        self.call_from_thread(
            self.notify,
            f"Password for {uname} ({email}) set to:\n{final_pw}",
            title="Password Reset Verified",
            timeout=15,
        )
        self.call_from_thread(self.set_status, f"Password reset for {uname}: {final_pw}")
        self.load_users()

    @work(thread=True)
    def _run_unlock_user(self) -> None:
        user = self._selected_user()
        if not user:
            return
        uid, uname = user["id"], user["username"]
        self.call_from_thread(self.set_status, f"Unlocking {uname}…")
        try:
            self.backend.unlock_account(uid)
        except Exception as exc:
            self.call_from_thread(self.set_status, str(exc), True)
            return
        self.call_from_thread(self.set_status, f"Cleared timeout/lockout for {uname}.")
        self.load_users()

    @work(thread=True)
    def _run_toggle_disable(self) -> None:
        user = self._selected_user()
        if not user:
            return
        uid, uname = user["id"], user["username"]
        new_state = not user.get("disabled", False)
        action = "Disabling" if new_state else "Enabling"
        self.call_from_thread(self.set_status, f"{action} {uname}…")
        try:
            self.backend.toggle_disable_account(uid, new_state)
        except Exception as exc:
            self.call_from_thread(self.set_status, str(exc), True)
            return
        self.call_from_thread(self.set_status, f"Account {uname} is now {'disabled' if new_state else 'enabled'}.")
        self.load_users()

    def _confirm_revoke_sessions(self) -> None:
        user = self._selected_user()
        if not user:
            return
        uid, uname = user["id"], user["username"]
        self.push_screen(
            ConfirmModal("Revoke Sessions", f"Force log out all active sessions for [bold]{uname}[/]?", "Revoke All"),
            lambda ok: ok and self._do_revoke_sessions(uid, uname),
        )

    @work(thread=True)
    def _do_revoke_sessions(self, uid: str, uname: str) -> None:
        self.call_from_thread(self.set_status, f"Revoking sessions for {uname}…")
        try:
            n = self.backend.revoke_sessions(uid)
        except Exception as exc:
            self.call_from_thread(self.set_status, str(exc), True)
            return
        self.call_from_thread(self.set_status, f"Revoked {n} session(s) for {uname}.")
        self.load_users()

    def _confirm_delete_user(self) -> None:
        user = self._selected_user()
        if not user:
            return
        uid, uname, email = user["id"], user["username"], user["email"]
        self.push_screen(
            ConfirmModal(
                "Delete Account Permanently",
                f"Delete [bold]{uname}[/] ({email})?\nRemoves account, profile, sessions, settings, and friend links.",
                "Delete",
            ),
            lambda ok: ok and self._do_delete_user(uid, uname),
        )

    @work(thread=True)
    def _do_delete_user(self, uid: str, uname: str) -> None:
        self.call_from_thread(self.set_status, f"Deleting {uname}…")
        try:
            self.backend.delete_account(uid)
        except Exception as exc:
            self.call_from_thread(self.set_status, str(exc), True)
            return
        self.call_from_thread(self.set_status, f"Deleted account {uname}.")
        self.load_users()

    @work(thread=True)
    def _run_mesh_friends(self) -> None:
        self.call_from_thread(self.set_status, "Auto-meshing all users as mutual friends…")
        try:
            n = self.backend.auto_mesh_friends()
        except Exception as exc:
            self.call_from_thread(self.set_status, str(exc), True)
            return
        self.call_from_thread(self.set_status, f"Auto-meshed {n} users as mutual friends.")
        if self.active_tab == "users":
            self.load_users()

    def _prompt_edit_limit(self) -> None:
        row = self._selected_config()
        if not row:
            return
        key, label, val, unit = row

        def _cb(raw: str | None) -> None:
            if not raw or not raw.strip():
                return
            try:
                parsed = parse_size_input(raw) if unit == "bytes" else int(raw.strip().replace("_", ""))
            except ValueError as exc:
                self.set_status(str(exc), True)
                return
            self._do_update_limit(key, label, parsed)

        hint = "Examples: 10GB, 50MB, 20971520" if unit == "bytes" else "Enter an integer value"
        self.push_screen(
            InputModal(
                f"Edit {label} ({key})",
                f"Current: [bold]{val}[/]\n{hint}\n(Will recreate autumn, api, and web)",
                default=str(val),
            ),
            _cb,
        )

    @work(thread=True)
    def _do_update_limit(self, key: str, label: str, val: int) -> None:
        self.call_from_thread(self.set_status, f"Updating {key} = {val:,} and recreating autumn/api/web…")
        try:
            self.backend.update_limit(key, val)
        except Exception as exc:
            self.call_from_thread(self.set_status, str(exc), True)
            return
        self.call_from_thread(self.set_status, f"Updated {label} to {val:,}.")
        self.load_config()

    @work(thread=True)
    def _run_inject(self) -> None:
        self.call_from_thread(self.set_status, "Running inject.js in stoat-web-1 & restarting Caddy…")
        try:
            self.backend.rerun_inject()
        except Exception as exc:
            self.call_from_thread(self.set_status, str(exc), True)
            return
        self.call_from_thread(self.set_status, "inject.js re-applied and Caddy restarted.")


def run() -> None:
    parser = argparse.ArgumentParser(prog="ss-tui", description="Stoat Server TUI")
    parser.add_argument("--host", default="", help="SSH host running Stoat (or set STOAT_SSH_HOST / ~/.config/ss-tui/config.json)")
    parser.add_argument("--dir", dest="stoat_dir", default="", help="Stoat compose directory (default: ~/stoat)")
    parser.add_argument("--local", action="store_true", help="Run commands locally instead of over SSH")
    args = parser.parse_args()

    backend = StoatBackend(host=args.host, stoat_dir=args.stoat_dir, local_mode=args.local)
    app = StoatServerApp(backend)
    app.run()


if __name__ == "__main__":
    run()
