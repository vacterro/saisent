"""SAISENT -- put a prompt into the agent sessions that are running right now.

The screen answers one question at a time: who is alive, what am I sending,
where is it in the queue. Everything that is a setting rather than a step --
schedule, quota gate, post-run action, dry run, tab override, debugger --
lives behind «Ещё...», because a control you touch once a month has no claim
on the space you look at every day.

All behaviour lives in `SAISENT_sessions/`: discovery, queues, delivery, quota
watching, the worker, the post-run actions. This file is the shell.
"""

from __future__ import annotations

import importlib.util
import json
import os
import queue
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from SAISENT_sessions import afterrun, appicon
from SAISENT_sessions.deliver import Deliverer, Win32Clipboard
from SAISENT_sessions.discover import (
    STATE_BUSY,
    AntigravityProvider,
    ClaudeCodeProvider,
    CodeNomadProvider,
    FreebuffProvider,
    SessionRegistry,
    process_running,
)
from SAISENT_sessions.limitwatch import LimitMonitor
from SAISENT_sessions.queues import (
    STATE_FAILED,
    STATE_PENDING,
    STATE_SENDING,
    STATE_SENT,
    QueueStore,
)
from SAISENT_sessions.worker import SendWorker  # re-exported for tests

try:
    import SAISENT_watcher.limits as limits
except ImportError:
    limits = None

APP_NAME = "SAISENT"
APP_VERSION = "4.0.0"
HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "SAISENT.json"
QUEUE_PATH = HERE / "SAISENT_QUEUES.json"
LOG_PATH = HERE / "SAISENT.log"
MUTEX_NAME = "Local\\SAISENT_SESSIONS_CONSOLE_SINGLE_INSTANCE"
ICON_SOURCE = Path(r"V:\___VAC\_PIC\_AVATARS\ARTIZEM\ARTIZEM_WHITE.png")
ICON_PATH = HERE / "SAISENT.ico"


def _load_core():
    """The proven Win32 layer and the Vintage Golden widgets."""
    for name in ("SAISENT_core.pyw",):
        path = HERE / name
        if not path.exists():
            continue
        spec = importlib.util.spec_from_file_location("saisent_gui_core", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules["saisent_gui_core"] = module
        spec.loader.exec_module(module)
        return module
    raise ImportError("cannot find the Win32 core next to SAISENT.pyw")


core = _load_core()
C = core.C
FONT = core.FONT
FONT_SMALL = core.FONT_SMALL
# Re-exported too: the tests never build a window, so a name missing here
# passes the whole suite and then crashes on the first real launch.
FONT_BUTTON = core.FONT_BUTTON
FONT_TITLE = core.FONT_TITLE

AGENTS = ("claude-code", "antigravity", "codenomad", "freebuff")
AGENT_LABELS = {
    "claude-code": "Claude Code",
    "antigravity": "Antigravity",
    "codenomad": "CodeNomad",
    "freebuff": "Freebuff",
}
STATE_TEXT = {"busy": "занята", "idle": "ждёт"}
ITEM_STATE_TEXT = {
    STATE_PENDING: "ждёт",
    STATE_SENDING: "шлётся",
    STATE_SENT: "ушло",
    STATE_FAILED: "ошибка",
}


# ------------------------------------------------------------------ config
class ConfigError(ValueError):
    """A key in SAISENT.json has a value the app cannot use.

    Raised with the offending key named, so the user fixes the right line
    instead of the app silently keeping a default that misbehaves later.
    """


class Config:
    defaults = {
        "version": 2,
        "agents": ["claude-code"],
        "tabs": {},
        "gap_ms": 1500,
        "submit": "ENTER",
        "auto_refresh": True,
        "refresh_seconds": 5,
        "freebuff_roots": [],
        "dry": False,
        "activation_timeout_ms": 10000,
        "key_delay_ms": 45,
        "settle_ms": 400,
        "confirm_seconds": 15,
        "busy_seconds": 20,
        "schedule_time": "",
        "check_limits": True,
        "after_run": "nothing",
        "tray_enabled": True,
        "cdp_titles": {},
        "cdp_profiles": {},
        # Per-agent reset rules: `daily HH:MM` / `rolling Nh` / `text`.
        # Empty means the shipped defaults in quota_plan.DEFAULT_PLANS.
        "quota_plans": {},
        # Saved prompt templates (T-051). Each may carry {session} / {project}
        # / {date} / {time} placeholders, expanded when inserted.
        "templates": [],
        "geometry": "880x600",
        "theme": "vintage",
    }

    # Schema-version steps (N -> N+1), keyed by the version being left. Each
    # step transforms the raw config dict; a step with no entry means the
    # newer schema only added keys, which `_migrate` fills with defaults.
    # v1 -> v2 added `theme`, `geometry` and `templates` as defaults, so the
    # step is a no-op here -- the mechanism exists for future breaking
    # changes (a renamed key, a reinterpreted value) that need real code.
    MIGRATIONS: dict[int, Callable[[dict], dict]] = {}

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = json.loads(json.dumps(self.defaults))

    # Keys that carry a duration or a delay: a 0 or negative value turns a
    # send into an instant burst or a timeout that never fires. Both break
    # silently at the use site, so they are schema errors on load.
    POSITIVE_KEYS = {
        "gap_ms",
        "refresh_seconds",
        "activation_timeout_ms",
        "key_delay_ms",
        "settle_ms",
        "confirm_seconds",
        "busy_seconds",
    }

    def _validate(self, key: str, fallback, value) -> None:
        """Raise ConfigError naming `key` when `value` cannot be used."""
        if isinstance(fallback, bool):
            if not isinstance(value, bool):
                raise ConfigError(
                    f"{key}: ожидается true/false, получено {value!r}"
                )
            return
        if isinstance(fallback, int):
            # bool is an int subclass in Python; JSON true/false must not
            # masquerade as a number.
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(
                    f"{key}: ожидается число, получено {value!r}"
                )
            if key in self.POSITIVE_KEYS and value <= 0:
                raise ConfigError(
                    f"{key}: должно быть больше 0, получено {value!r}"
                )
            return
        if isinstance(fallback, str):
            if not isinstance(value, str):
                raise ConfigError(
                    f"{key}: ожидается текст, получено {value!r}"
                )
            if key == "schedule_time" and value:
                try:
                    hour, minute = (int(part) for part in value.split(":", 1))
                    if not (0 <= hour <= 23 and 0 <= minute <= 59):
                        raise ValueError
                except ValueError:
                    raise ConfigError(
                        f"{key}: ожидается HH:MM, получено {value!r}"
                    )
            return
        if isinstance(fallback, list) and not isinstance(value, list):
            raise ConfigError(
                f"{key}: ожидается список, получено {value!r}"
            )
        if isinstance(fallback, dict) and not isinstance(value, dict):
            raise ConfigError(
                f"{key}: ожидается объект, получено {value!r}"
            )

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            raise ConfigError("SAISENT.json: корень должен быть объектом JSON")
        raw_version = raw.get("version", 1)
        try:
            file_version = int(raw_version)
        except (TypeError, ValueError):
            file_version = 1
        current = int(self.defaults["version"])
        if file_version < current:
            # An older app wrote this file. Advance it to the current schema
            # and rewrite it, so the file self-heals instead of staying one
            # schema behind forever. A failed write just leaves it stale; the
            # in-memory migration still applies.
            raw = self._migrate(raw, file_version)
            self._write(raw)
        elif file_version > current:
            # A newer app wrote this file. Load every key we know and never
            # downgrade the file: the version stays untouched so the newer
            # app that owns it is not clobbered.
            pass
        for key, fallback in self.defaults.items():
            if key not in raw:
                continue
            self._validate(key, fallback, raw[key])
            self.data[key] = raw[key]

    def _migrate(self, raw: dict, from_version: int) -> dict:
        """Advance a config file to the current schema, one step at a time."""
        current = int(self.defaults["version"])
        migrated = dict(raw)
        for version in range(from_version, current):
            step = self.MIGRATIONS.get(version)
            if step is not None:
                migrated = step(migrated)
            for key, fallback in self.defaults.items():
                if key not in migrated:
                    migrated[key] = json.loads(json.dumps(fallback))
            migrated["version"] = version + 1
        return migrated

    def save(self) -> bool:
        return self._write(self.data)

    def _write(self, raw: dict) -> bool:
        temp = self.path.with_suffix(".json.tmp")
        try:
            temp.write_text(
                json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(temp, self.path)
        except OSError:
            return False
        return True

    def __getitem__(self, key):
        return self.data.get(key, self.defaults.get(key))

    def __setitem__(self, key, value):
        self.data[key] = value


# ------------------------------------------------------------------- theme
def configure_theme(root: tk.Misc) -> None:
    core.configure_ttk(root)
    style = ttk.Style(root)
    style.configure(
        "Vintage.Treeview",
        font=FONT_SMALL,
        background=C["compareBack"],
        fieldbackground=C["compareBack"],
        foreground=C["textPrimary"],
        borderwidth=0,
        rowheight=20,
    )
    style.map(
        "Vintage.Treeview",
        background=[("selected", C["selection"])],
        foreground=[("selected", C["textPrimary"])],
    )
    style.configure(
        "Vintage.Treeview.Heading",
        font=FONT_SMALL,
        background=C["surfaceRaised"],
        foreground=C["textSecondary"],
        relief="raised",
        borderwidth=2,
    )
    style.layout("Vintage.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])


def group(parent: tk.Misc, text: str) -> tk.LabelFrame:
    return tk.LabelFrame(
        parent,
        text=text,
        font=FONT_SMALL,
        bg=C["surfaceRaised"],
        fg=C["textSecondary"],
        relief="raised",
        bd=2,
        padx=5,
        pady=4,
    )


def expand_template(text: str, session) -> str:
    """Expand a prompt template's {placeholders} for the selected session.

    {session} -> the session name, {project} -> its project slug,
    {date} -> YYYY-MM-DD, {time} -> HH:MM local. Unknown placeholders are
    left alone rather than silently eaten -- a typo stays visible in the box
    instead of vanishing into a send.
    """
    now = datetime.now()
    name = getattr(session, "name", "") or ""
    project = getattr(session, "project_name", None)
    if project is None:
        project = getattr(session, "project", "") or ""
    out = text.replace("{date}", now.strftime("%Y-%m-%d")).replace(
        "{time}", now.strftime("%H:%M")
    )
    # A placeholder we cannot fill stays literal -- no session means
    # {session}/{project} have nothing to expand to, and eating them would
    # silently drop the user's intent.
    if name:
        out = out.replace("{session}", name)
    if project:
        out = out.replace("{project}", project)
    return out


def age_text(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}с"
    if seconds < 3600:
        return f"{seconds // 60}м"
    if seconds < 86400:
        return f"{seconds // 3600}ч"
    return f"{seconds // 86400}д"


def batch_done_notice(sent: int, reason: str):
    """What a finished batch should announce: (title, text, warn) or None.

    The worker's done event carries `(sent, reason)` where the reason already
    names the trouble ("готово, 1 с ошибкой...", "не подтверждено",
    "пропущено"). A stopped batch announces nothing -- the user stopped it
    themselves and a balloon would just be noise. A clean batch gets a quiet
    info balloon; one with any trouble gets a warning balloon plus a bell.
    Pure on purpose: the whole matrix is testable without a window.
    """
    if not reason or "остановлено" in reason:
        return None
    trouble = any(mark in reason for mark in (
        "с ошибкой", "не подтверждено", "пропущено", "сбой"
    ))
    if trouble:
        return (
            "SAISENT — не всё отправлено",
            f"Отправлено {sent}: {reason}",
            True,
        )
    return ("SAISENT — готово", f"Отправлено {sent}: {reason}", False)


def next_fire_label(schedule_time: str, global_time: str = "", now=None) -> str:
    """What a queue row should say about when it fires (T-062).

    A session's own HH:MM wins over the global one; an empty effective time
    means "now". Uses the same `next_occurrence` the worker sorts by, so the
    display cannot disagree with the send. An unreadable time says so instead
    of pretending to be "now".
    """
    effective = (schedule_time or global_time or "").strip()
    if not effective:
        return "сейчас"
    target = SendWorker.next_occurrence(effective, now)
    if target is None:
        return f"нечитаемое ({effective!r})"
    today = (now or datetime.now()).date()
    day = "сегодня" if target.date() == today else "завтра"
    return f"{effective} ({day})"


# ------------------------------------------------------------------ the app
class SaisentApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.api = core.WindowsAPI()
        self.config_store = Config(CONFIG_PATH)
        try:
            self.config_store.load()
        except ConfigError as exc:
            # A bad SAISENT.json must not take the app down, but it also
            # must not be swallowed: name the key, then run on defaults so
            # the user can fix the file and restart.
            self.log(f"SAISENT.json: {exc} — работаю с настройками по умолчанию.")
            self.config_store = Config(CONFIG_PATH)
        theme_name = str(self.config_store["theme"])
        if theme_name in core.THEMES:
            C.update(core.THEMES[theme_name])
        self.queues = QueueStore(QUEUE_PATH)
        self.queues.load()

        self.ui_queue: queue.Queue = queue.Queue()
        self.sessions: list = []
        self.sessions_by_key: dict = {}
        self.selected_key: str | None = None
        self.closing = False
        self._force_quit = False
        self._sidebar_cache: dict = {}
        self._queue_cache: tuple = ()
        self._drag_item: str | None = None
        self._auto_after: str | None = None
        self._limit_after: str | None = None
        self._limit_scanning = False
        self._limit_rescan_pending = False
        self._cdp_ports: dict = {}
        self._editing_id: str | None = None
        self._undo_item: tuple[str, str] | None = None
        self._undo_after: str | None = None

        self.registry = self._build_registry()
        self.deliverer = Deliverer(
            self.api,
            clipboard=Win32Clipboard(),
            activity=self.activity_of,
            activation_timeout_ms=int(self.config_store["activation_timeout_ms"]),
            key_delay_ms=int(self.config_store["key_delay_ms"]),
            settle_ms=int(self.config_store["settle_ms"]),
            submit=str(self.config_store["submit"] or "ENTER"),
            confirm_timeout=float(self.config_store["confirm_seconds"]),
            cdp_sender_factory=self._build_cdp_factory(),
            cdp_titles=dict(self.config_store["cdp_titles"] or {}),
            activity_map=self.activity_snapshot,
        )
        self.worker = SendWorker(self.deliverer, self.ui_queue.put, self.registry)
        self.limit_monitor = LimitMonitor(
            self.registry, limits.scan_text if limits else (lambda _t: None)
        )
        self.worker.limit_monitor = self.limit_monitor

        # Settings live in vars so «Ещё...» can bind straight to them.
        self.schedule_var = tk.StringVar(value=str(self.config_store["schedule_time"]))
        self.limits_var = tk.BooleanVar(value=bool(self.config_store["check_limits"]))
        self.dry_var = tk.BooleanVar(value=bool(self.config_store["dry"]))
        self.tray_var = tk.BooleanVar(value=bool(self.config_store["tray_enabled"]))
        self.theme_var = tk.StringVar(value=str(self.config_store["theme"]))
        self.after_var = tk.StringVar(
            value=afterrun.label_for(str(self.config_store["after_run"]))
        )
        self.auto_var = tk.BooleanVar(value=bool(self.config_store["auto_refresh"]))

        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry(str(self.config_store["geometry"]))
        self.minsize(640, 480)
        self.configure(bg=C["background"])
        configure_theme(self)
        self.icon_path = appicon.ensure_ico(ICON_SOURCE, ICON_PATH)
        appicon.apply_window_icon(self, self.icon_path)
        self._build_ui()

        tray_class = appicon.make_tray_class(core.TrayIcon)
        self.tray = tray_class(
            self.api.user32,
            self.api.kernel32,
            self._tray_restore,
            self._tray_quit,
            ico_path=self.icon_path,
        )
        if not self.tray.start(APP_NAME):
            self.log("Трей не запустился — иконка и уведомления будут недоступны.")

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(120, self.pump)
        self.refresh_sessions()
        self.apply_auto_refresh()
        self.tick_limits()
        self.log(f"{APP_NAME} {APP_VERSION} запущен.")

    # ---- wiring ------------------------------------------------------
    def _build_registry(self) -> SessionRegistry:
        busy = float(self.config_store["busy_seconds"])
        return SessionRegistry(
            providers=[
                ClaudeCodeProvider(busy_seconds=busy, log=self.log),
                AntigravityProvider(busy_seconds=busy, log=self.log),
                CodeNomadProvider(busy_seconds=busy, log=self.log),
                FreebuffProvider(
                    roots=list(self.config_store["freebuff_roots"] or []),
                    busy_seconds=busy,
                    running=process_running,
                    log=self.log,
                ),
            ],
            enabled=set(self.config_store["agents"] or ["claude-code"]),
            log=self.log,
        )

    def _build_cdp_factory(self):
        try:
            from SAISENT_watcher.cdp import CdpSender
        except ImportError:
            return None
        overrides = self.config_store["cdp_profiles"] or {}

        def factory(profile: dict):
            merged = dict(profile)
            merged.update(overrides.get(profile.get("agent", ""), {}))
            return CdpSender(
                submit=str(merged.get("submit") or "enter").lower(),
                multiline="join",
                selector=str(merged.get("selector") or ""),
                dialog_selector=str(merged.get("dialog_selector") or ""),
                dialog_attr=str(merged.get("dialog_attr") or ""),
            )

        return factory

    def activity_of(self, key: str) -> float:
        session = self.sessions_by_key.get(key)
        if session is None:
            return 0.0
        try:
            for fresh in self.registry.discover():
                if fresh.key == key:
                    return fresh.last_active
        except Exception as exc:
            self.log(f"Обновление активности сессии не удалось: {exc}")
        return session.last_active

    # ---- layout ------------------------------------------------------
    def _build_ui(self) -> None:
        root = tk.Frame(self, bg=C["background"])
        root.pack(fill="both", expand=True, padx=6, pady=6)

        agents = group(root, " Агенты ")
        agents.pack(fill="x")
        self.agent_vars = {}
        for agent in AGENTS:
            var = tk.BooleanVar(value=self.registry.is_enabled(agent))
            self.agent_vars[agent] = var
            core.vcheck(
                agents,
                variable=var,
                text=AGENT_LABELS[agent],
                command=lambda a=agent: self.toggle_agent(a),
            ).pack(side="left", padx=(0, 12))
        self.sessions_note_var = tk.StringVar(value="")
        core.vlabel(
            agents, textvariable=self.sessions_note_var, muted=True, small=True
        ).pack(side="right")

        body = tk.Frame(root, bg=C["background"])
        body.pack(fill="both", expand=True, pady=(6, 0))
        self._build_sessions(body)
        self._build_right(body)
        self._build_status(root)

    def _build_sessions(self, parent) -> None:
        box = group(parent, " Сессии ")
        box.pack(side="left", fill="y")

        holder = tk.Frame(box, bg=C["compareBack"], bd=2, relief="sunken")
        holder.pack(fill="both", expand=True)
        self.session_tree = ttk.Treeview(
            holder,
            columns=("name", "where"),
            show="headings",
            selectmode="browse",
            style="Vintage.Treeview",
            height=16,
        )
        self.session_tree.heading("name", text="Сессия")
        self.session_tree.heading("where", text="Проект · состояние")
        self.session_tree.column("name", width=150, anchor="w", stretch=False)
        self.session_tree.column("where", width=210, anchor="w", stretch=False)
        self.session_tree.tag_configure("busy", foreground=C["warning"])
        self.session_tree.tag_configure("idle", foreground=C["textPrimary"])
        self.session_tree.tag_configure("queued", background=C["surface"])
        # Pending work whose session is gone: visible, but plainly not live.
        self.session_tree.tag_configure("orphan", foreground=C["danger"])
        self.session_tree.pack(side="left", fill="both", expand=True)
        self.session_tree.bind("<<TreeviewSelect>>", self.on_session_selected)

        bar = ttk.Scrollbar(
            holder,
            orient="vertical",
            command=self.session_tree.yview,
            style="Vintage.Vertical.TScrollbar",
        )
        bar.pack(side="left", fill="y")
        self.session_tree.configure(yscrollcommand=bar.set)

        row = core.vframe(box)
        row.pack(fill="x", pady=(5, 0))
        core.vbutton(row, "Обновить", self.refresh_sessions, width=10).pack(side="left")
        core.vcheck(
            row, variable=self.auto_var, text="сам", command=self.apply_auto_refresh
        ).pack(side="left", padx=(6, 0))

    def _build_right(self, parent) -> None:
        right = tk.Frame(parent, bg=C["background"])
        right.pack(side="left", fill="both", expand=True, padx=(6, 0))

        text_box = group(right, " Что отправить ")
        text_box.pack(fill="x")
        self.text_box = tk.Text(
            text_box,
            height=7,
            font=FONT_SMALL,
            bg=C["compareBack"],
            fg=C["textPrimary"],
            insertbackground=C["textPrimary"],
            selectbackground=C["selection"],
            relief="sunken",
            bd=2,
            wrap="word",
            undo=True,
            highlightthickness=0,
        )
        self.text_box.pack(fill="x")
        self.text_box.bind("<Control-Return>", self.on_ctrl_enter)
        self.text_box.bind("<Control-Shift-Return>", lambda e: (self.send_all(), "break")[1])
        self.text_box.bind("<Escape>", lambda e: self.cancel_edit() or "break")
        self.bind_all("<Control-l>", lambda e: self.text_box.focus_set() or "break")
        for n in range(1, 10):
            self.bind_all(f"<Control-Key-{n}>", self._make_jump(n))

        self.normal_actions = core.vframe(text_box)
        self.normal_actions.pack(fill="x", pady=(5, 0))
        self.edit_actions = core.vframe(text_box)
        
        self.send_text_button = core.vbutton(
            self.normal_actions, "Текст сейчас", self.send_text_now, role="primary", width=13
        )
        self.send_text_button.pack(side="left")
        core.vbutton(self.normal_actions, "В очередь", self.add_to_queue, width=10).pack(side="left", padx=(4, 0))
        core.vbutton(self.normal_actions, "Всем", self.add_to_all_queues, width=6).pack(side="left", padx=(4, 0))
        
        self.templates_menubutton = tk.Menubutton(
            self.normal_actions,
            text="Шаблоны ▾",
            font=FONT_BUTTON,
            bg=C["surfaceRaised"],
            fg=C["textPrimary"],
            activebackground=C["surfaceAlt"],
            activeforeground=C["textPrimary"],
            relief="raised",
            bd=2,
            highlightthickness=0,
        )
        self.templates_menubutton.pack(side="left", padx=(4, 0))
        self.templates_menu = tk.Menu(
            self.templates_menubutton, tearoff=0, bg=C["surface"],
            fg=C["textPrimary"], activebackground=C["surfaceAlt"],
            activeforeground=C["textPrimary"],
        )
        self.templates_menubutton.configure(menu=self.templates_menu)
        self.rebuild_templates_menu()
        core.vbutton(self.normal_actions, "Очистить", self.clear_text, width=9).pack(side="right")
        
        self.edit_label_var = tk.StringVar(value="Правка:")
        core.vlabel(self.edit_actions, textvariable=self.edit_label_var, small=True).pack(side="left", padx=(0, 8))
        core.vbutton(self.edit_actions, "Сохранить правку", self.save_edit, role="primary", width=16).pack(side="left")
        core.vbutton(self.edit_actions, "Отменить правку", self.cancel_edit, width=16).pack(side="left", padx=(4, 0))

        self.queue_box = group(right, " Очередь ")
        self.queue_box.pack(fill="both", expand=True, pady=(6, 0))
        holder = tk.Frame(self.queue_box, bg=C["compareBack"], bd=2, relief="sunken")
        holder.pack(fill="both", expand=True)
        self.queue_tree = ttk.Treeview(
            holder,
            # Must list every column the loop below configures: a heading for
            # a column that is not declared raises `Invalid column index` and
            # the whole window fails to build.
            columns=("num", "state", "fire", "text"),
            show="headings",
            selectmode="browse",
            style="Vintage.Treeview",
            height=7,
        )
        for column, title, width, stretch in (
            ("num", "#", 28, False),
            ("state", "Статус", 70, False),
            ("fire", "Когда", 100, False),
            ("text", "Промпт", 340, True),
        ):
            self.queue_tree.heading(column, text=title)
            self.queue_tree.column(column, width=width, stretch=stretch, anchor="w")
        self.queue_tree.tag_configure("sent", foreground=C["textMuted"])
        self.queue_tree.tag_configure("failed", foreground=C["danger"])
        self.queue_tree.tag_configure("pending", foreground=C["textPrimary"])
        self.queue_tree.tag_configure("sending", foreground=C["warning"])
        self.queue_tree.pack(side="left", fill="both", expand=True)
        self.queue_tree.bind("<ButtonPress-1>", self.on_drag_start)
        self.queue_tree.bind("<B1-Motion>", self.on_drag_motion)
        self.queue_tree.bind("<ButtonRelease-1>", self.on_drag_drop)
        self.queue_tree.bind("<Double-Button-1>", self.on_queue_double_click)

        bar = ttk.Scrollbar(
            holder,
            orient="vertical",
            command=self.queue_tree.yview,
            style="Vintage.Vertical.TScrollbar",
        )
        bar.pack(side="left", fill="y")
        self.queue_tree.configure(yscrollcommand=bar.set)

        row = core.vframe(self.queue_box)
        row.pack(fill="x", pady=(5, 0))
        for label, command, width in (
            ("Выше", lambda: self.move_item(-1), 6),
            ("Ниже", lambda: self.move_item(1), 6),
            ("Править", self.edit_item, 8),
            ("Копия", self.duplicate_item, 6),
            ("Удалить", self.remove_item, 8),
            ("Очистка...", self.show_cleanup_dialog, 11),
            ("Экспорт", self.export_queues, 9),
            ("Импорт", self.import_queues, 9),
        ):
            core.vbutton(row, label, command, width=width).pack(
                side="left", padx=(0, 3)
            )
            
        batch_row = core.vframe(self.queue_box)
        batch_row.pack(fill="x", pady=(5, 0))
        self.send_queue_button = core.vbutton(batch_row, "Очередь сейчас", self.send_selected, width=15, role="primary")
        self.send_queue_button.pack(side="left")
        self.send_all_button = core.vbutton(batch_row, "Все очереди сейчас", self.send_all, width=18)
        self.send_all_button.pack(side="left", padx=(4, 0))
        self.stop_button = core.vbutton(
            batch_row, "СТОП", self.stop_send, role="danger", width=6, state="disabled"
        )
        self.stop_button.pack(side="right")
        self.undo_button = core.vbutton(
            batch_row, "Отменить", self.undo_last_send, width=10
        )
        self.undo_button.pack(side="right", padx=(0, 4))
        self.undo_button.pack_forget()

        sched = core.vframe(self.queue_box)
        sched.pack(fill="x", pady=(2, 0))
        self.session_time_var = tk.StringVar(value="")
        core.vlabel(
            sched, text="Своё время (HH:MM):", small=True, muted=True
        ).pack(side="left")
        core.ventry(sched, textvariable=self.session_time_var, width=7).pack(
            side="left", padx=(4, 4)
        )
        core.vbutton(sched, "Задать", self.set_session_time, width=8).pack(
            side="left"
        )
        core.vlabel(
            sched,
            text="или наследует общее расписание",
            small=True,
            muted=True,
        ).pack(side="left", padx=(6, 0))

    def _build_status(self, root) -> None:
        bar = tk.Frame(root, bg=C["background"])
        bar.pack(fill="x", pady=(6, 0))

        self.status_state_var = tk.StringVar(value="IDLE")
        self.status_state_label = tk.Label(
            bar,
            textvariable=self.status_state_var,
            font=FONT_SMALL,
            bg=C["background"],
            fg=C["textSecondary"],
            width=8,
            anchor="w",
        )
        self.status_state_label.pack(side="left")

        self.status_var = tk.StringVar(value="Готово.")
        tk.Label(
            bar,
            textvariable=self.status_var,
            font=FONT_SMALL,
            bg=C["compareBack"],
            fg=C["textPrimary"],
            relief="sunken",
            bd=2,
            anchor="w",
            padx=4,
        ).pack(side="left", fill="x", expand=True)

        core.vbutton(bar, "Журнал", self.open_log, width=8).pack(side="right")
        core.vbutton(bar, "История", self.show_history, width=8).pack(
            side="right", padx=(0, 4)
        )
        core.vbutton(bar, "Ещё...", self.show_more, width=8).pack(
            side="right", padx=(0, 4)
        )

    # ---- sessions ----------------------------------------------------
    def toggle_agent(self, agent: str) -> None:
        self.registry.enable(agent, bool(self.agent_vars[agent].get()))
        self.config_store["agents"] = sorted(self.registry.enabled)
        self.config_store.save()
        self.refresh_sessions()

    def apply_auto_refresh(self) -> None:
        if self._auto_after is not None:
            self.after_cancel(self._auto_after)
            self._auto_after = None
        self.config_store["auto_refresh"] = bool(self.auto_var.get())
        self.config_store.save()
        if self.auto_var.get():
            self._schedule_auto()

    def _schedule_auto(self) -> None:
        if self.closing or not self.auto_var.get():
            return
        seconds = max(2, int(self.config_store["refresh_seconds"]))
        self._auto_after = self.after(seconds * 1000, self._auto_tick)

    def _auto_tick(self) -> None:
        self._auto_after = None
        if self.closing:
            return
        if not self.worker.running:
            self.refresh_sessions()
        self._schedule_auto()

    def refresh_sessions(self) -> None:
        now = time.time()
        try:
            found = self.registry.discover(now)
        except Exception as exc:
            self.set_status("ERROR", f"Опрос сессий не удался: {exc}")
            return
        self.sessions = found
        self.sessions_by_key = {s.key: s for s in found}

        overrides = self.config_store["tabs"] or {}
        for session in found:
            override = overrides.get(session.key)
            if isinstance(override, int):
                session.tab_hint = override

        self.render_sessions(now)
        busy = sum(1 for s in found if s.state == STATE_BUSY)
        pending = self.queues.total_pending()
        orphans = len(self.orphan_queues())
        note = (
            f"{len(found)} живых · {busy} заняты · {pending} в очередях"
            if found
            else "живых сессий нет"
        )
        if orphans:
            note += f" · {orphans} без сессии"
        self.sessions_note_var.set(note)
        if self.selected_key not in self.sessions_by_key:
            self.selected_key = found[0].key if found else None
        self.select_session(self.selected_key)
        self.render_queue()

    def orphan_queues(self) -> list:
        """Queues holding pending work whose session is gone.

        Without these the prompts are invisible AND unsendable: the sidebar
        only lists live sessions, so the rows vanish while the queue file
        still carries the items. Found 11 such prompts sitting in two dead
        keys. Shown as unreachable rows so they can be seen, moved or deleted.
        """
        return [
            key
            for key in self.queues.queues
            if key not in self.sessions_by_key and self.queues.pending(key)
        ]

    def render_sessions(self, now: float) -> None:
        tree = self.session_tree
        wanted = []
        for session in self.sessions:
            pending = len(self.queues.pending(session.key))
            name = session.name if not pending else f"{session.name}  [{pending}]"
            where = (
                f"{session.project_name} · "
                f"{STATE_TEXT.get(session.state, session.state)} "
                f"{age_text(session.age_seconds(now))}"
            )
            tags = [session.state] + (["queued"] if pending else [])
            wanted.append((session.key, (name, where), tuple(tags)))

        for key in self.orphan_queues():
            pending = len(self.queues.pending(key))
            label = self.queues.labels.get(key) or key.split(":", 1)[-1][:12]
            agent = key.split(":", 1)[0]
            wanted.append(
                (
                    key,
                    (f"{label}  [{pending}]", f"{agent} · сессии нет"),
                    ("orphan",),
                )
            )

        current = list(tree.get_children(""))
        if [key for key, _v, _t in wanted] != current:
            tree.delete(*current)
            for key, values, tags in wanted:
                tree.insert("", "end", iid=key, values=values, tags=tags)
            self._sidebar_cache = {k: (v, t) for k, v, t in wanted}
            return
        for key, values, tags in wanted:
            if self._sidebar_cache.get(key) == (values, tags):
                continue
            tree.item(key, values=values, tags=tags)
            self._sidebar_cache[key] = (values, tags)

    def select_session(self, key: str | None) -> None:
        if key and self.session_tree.exists(key):
            if self.session_tree.selection() != (key,):
                self.session_tree.selection_set(key)
            self.selected_key = key
        session = self.sessions_by_key.get(key or "")
        self.queue_box.configure(
            text=f" Очередь — {session.name} " if session else " Очередь "
        )
        # Show the session's own send time (or clear the field to say it
        # inherits the global one).
        self.session_time_var.set(self.queues.schedule_of(key or ""))

    def on_session_selected(self, _event=None) -> None:
        selection = self.session_tree.selection()
        if not selection:
            return
        if self._editing_id and selection[0] != self.selected_key:
            self.cancel_edit()
        self.selected_key = selection[0]
        self.select_session(self.selected_key)
        self.render_queue()

    # ---- queue -------------------------------------------------------
    def render_queue(self) -> None:
        tree = self.queue_tree
        items = self.queues.items(self.selected_key or "")
        snapshot = tuple(
            (i.id, i.state, i.label, i.reason, i.confirmed) for i in items
        )
        if snapshot == self._queue_cache:
            return
        self._queue_cache = snapshot
        selected = tree.selection()
        tree.delete(*tree.get_children(""))
        # One fire time for the whole queue: the selected session's own
        # HH:MM wins, otherwise the global schedule, otherwise "now". Same
        # next_occurrence the worker sorts by, so the row cannot lie (T-062).
        own = self.queues.schedule_of(self.selected_key or "")
        fire = next_fire_label(own, str(self.schedule_var.get() or ""))
        for index, item in enumerate(items, start=1):
            label = item.label
            if item.state == STATE_FAILED and item.reason:
                label = f"{label}   << {item.reason}"
            state = ITEM_STATE_TEXT.get(item.state, item.state)
            if item.state == STATE_SENT and not item.confirmed:
                state = "ушло?"
            tree.insert(
                "",
                "end",
                iid=item.id,
                values=(index, state, fire, label),
                tags=(item.state,),
            )
        if selected and tree.exists(selected[0]):
            tree.selection_set(selected[0])

    def current_text(self) -> str:
        return self.text_box.get("1.0", "end-1c").strip()

    def clear_text(self) -> None:
        self.text_box.delete("1.0", "end")

    def on_ctrl_enter(self, _event) -> str:
        if self._editing_id:
            self.save_edit()
        else:
            self.send_text_now()
        return "break"

    def _make_jump(self, n: int):
        def jump(_event=None):
            children = self.session_tree.get_children("")
            if 0 < n <= len(children):
                item = children[n - 1]
                self.session_tree.selection_set(item)
                self.session_tree.see(item)
                self.on_session_selected()
            return "break"
        return jump

    def busy_now(self) -> bool:
        if self.worker.running and getattr(self.worker, "phase", "") != "waiting":
            self.set_status("ERROR", "Идёт отправка — очередь сейчас не трогаем.")
            return True
        return False

    def add_to_queue(self) -> None:
        text = self.current_text()
        if not text:
            self.set_status("ERROR", "Поле пустое.")
            return
        if not self.selected_key:
            self.set_status("ERROR", "Не выбрана сессия.")
            return
        session = self.sessions_by_key.get(self.selected_key)
        self.queues.add(self.selected_key, text, label=session.name if session else "")
        self.queues.save()
        self.cancel_edit()
        self.clear_text()
        self._queue_cache = ()
        self.render_queue()
        self.render_sessions(time.time())
        self.set_status("IDLE", f"В очередь: {session.name if session else ''}.")

    def add_to_all_queues(self) -> None:
        text = self.current_text()
        if not text:
            self.set_status("ERROR", "Поле пустое.")
            return
        if not self.sessions:
            self.set_status("ERROR", "Живых сессий нет.")
            return
        for session in self.sessions:
            self.queues.add(session.key, text, label=session.name)
        self.queues.save()
        self.cancel_edit()
        self.clear_text()
        self._queue_cache = ()
        self.render_queue()
        self.render_sessions(time.time())
        self.set_status("IDLE", f"В очередь ко всем: {len(self.sessions)}.")

    def selected_item_id(self) -> str | None:
        selection = self.queue_tree.selection()
        return selection[0] if selection else None

    def move_item(self, delta: int) -> None:
        item_id = self.selected_item_id()
        if not item_id or not self.selected_key or self.busy_now():
            return
        if self.queues.move(self.selected_key, item_id, delta):
            self.queues.save()
            self._queue_cache = ()
            self.render_queue()
            self.queue_tree.selection_set(item_id)

    def remove_item(self) -> None:
        item_id = self.selected_item_id()
        if not item_id or not self.selected_key or self.busy_now():
            return
        if self._editing_id == item_id:
            self.cancel_edit()
        if self.queues.remove(self.selected_key, item_id):
            self.queues.save()
            self._queue_cache = ()
            self.render_queue()
            self.render_sessions(time.time())

    def on_queue_double_click(self, _event) -> str:
        self.edit_item()
        return "break"

    def duplicate_item(self) -> None:
        item_id = self.selected_item_id()
        if not item_id or not self.selected_key or self.busy_now():
            return
        clone = self.queues.duplicate(self.selected_key, item_id)
        if clone:
            self.queues.save()
            self._queue_cache = ()
            self.render_queue()
            self.render_sessions(time.time())
            self.queue_tree.selection_set(clone.id)

    def show_cleanup_dialog(self) -> None:
        if not self.selected_key:
            return
        window = tk.Toplevel(self)
        window.title("Очистка")
        window.configure(bg=C["background"])
        window.transient(self)
        window.grab_set()
        
        session = self.sessions_by_key.get(self.selected_key)
        name = session.name if session else "выбранной сессии"
        
        core.vlabel(window, text="Очистка очередей", font=FONT_TITLE).pack(pady=(10, 5))

        def confirm_and_run(desc, count, action):
            if not messagebox.askyesno("Очистка", f"Удалить {count} элементов?\n\n{desc}\n\nЭто действие необратимо. Продолжить?", parent=window, default="no"):
                return
            window.destroy()
            action()

        def do_clear_finished():
            count = sum(1 for i in self.queues.items(self.selected_key) if i.state not in (STATE_PENDING, STATE_FAILED))
            if not count:
                self.set_status("IDLE", "Нет завершённых элементов.")
                return
            confirm_and_run(f"Завершённые элементы из очереди {name}.", count, lambda: (self.queues.clear_finished(self.selected_key), self.after_cleanup()))

        def do_clear():
            count = len(self.queues.items(self.selected_key))
            if not count:
                self.set_status("IDLE", "Очередь пуста.")
                return
            confirm_and_run(f"ВСЕ элементы из очереди {name}, включая ожидающие отправки.", count, lambda: (self.queues.clear(self.selected_key), self.after_cleanup()))

        def do_clear_all():
            count = sum(len(items) for items in self.queues.queues.values())
            if not count:
                self.set_status("IDLE", "Все очереди пусты.")
                return
            confirm_and_run("ВСЕ элементы из ВСЕХ очередей всех сессий, включая ожидающие отправки.", count, lambda: (self.queues.clear_all_queues(), self.after_cleanup()))

        def do_requeue():
            count = sum(1 for i in self.queues.items(self.selected_key) if i.state in (STATE_SENT, STATE_FAILED))
            if not count:
                self.set_status("IDLE", "Нет элементов для возврата в очередь.")
                return
            if messagebox.askyesno("SAISENT", f"Вернуть {count} элементов в ожидание в очереди {name}?", parent=window):
                self.queues.requeue_all(self.selected_key)
                self.after_cleanup()
                window.destroy()

        box = core.vframe(window)
        box.pack(padx=20, pady=10, fill="x")
        core.vbutton(box, "Очистить завершённые (текущая)", do_clear_finished, width=35).pack(pady=3)
        core.vbutton(box, "Вернуть завершённые/ошибки (текущая)", do_requeue, width=35).pack(pady=3)
        core.vbutton(box, "Очистить ВСЮ текущую очередь", do_clear, width=35, role="danger").pack(pady=3)
        core.vbutton(box, "Очистить ВООБЩЕ ВСЕ очереди", do_clear_all, width=35, role="danger").pack(pady=3)

    def export_queues(self) -> None:
        total = sum(len(items) for items in self.queues.queues.values())
        if not total:
            self.set_status("IDLE", "Все очереди пусты — нечего экспортировать.")
            return
        path = filedialog.asksaveasfilename(
            title="Экспорт очередей",
            defaultextension=".jsonl",
            filetypes=[("JSONL", "*.jsonl"), ("All", "*.*")],
            initialfile="saisent_queues.jsonl",
        )
        if not path:
            return
        written = self.queues.export_jsonl(path)
        self.set_status("IDLE", f"Экспорт: {written} элементов в {Path(path).name}.")

    def import_queues(self) -> None:
        path = filedialog.askopenfilename(
            title="Импорт очередей",
            filetypes=[("JSONL", "*.jsonl"), ("All", "*.*")],
        )
        if not path:
            return
        added = self.queues.import_jsonl(path)
        if added:
            self.queues.save()
            self.after_cleanup()
            self.set_status("IDLE", f"Импорт: {added} новых элементов добавлено.")
        else:
            self.set_status("IDLE", "Импорт: нет новых элементов (все уже есть или файл пуст).")

    def undo_last_send(self) -> None:
        if self._undo_item is None:
            return
        key, item_id = self._undo_item
        item = self.queues.find(key, item_id)
        if item is None or item.state != STATE_SENT:
            self.set_status("IDLE", "Отмена невозможна: промпт уже не в статусе 'отправлен'.")
            self._undo_item = None
            self.undo_button.pack_forget()
            return
        if item.confirmed:
            self.set_status("IDLE", "Отмена невозможна: сессия уже обработала промпт.")
            self._undo_item = None
            self.undo_button.pack_forget()
            return
        item.state = STATE_PENDING
        item.reason = ""
        item.sent_at = ""
        item.confirmed = False
        self.queues.save()
        self._undo_item = None
        self._cancel_undo_timer()
        if hasattr(self, "undo_button"):
            try:
                self.undo_button.pack_forget()
            except tk.TclError:
                pass
        self._queue_cache = ()
        self.render_queue()
        self.render_sessions(time.time())
        self.set_status("IDLE", "Отменено: промпт возвращён в очередь.")

    def _cancel_undo_timer(self) -> None:
        if self._undo_after is not None:
            if hasattr(self, "after_cancel"):
                self.after_cancel(self._undo_after)
            self._undo_after = None

    def _hide_undo_button(self) -> None:
        self._undo_item = None
        self._undo_after = None
        if hasattr(self, "undo_button"):
            try:
                self.undo_button.pack_forget()
            except tk.TclError:
                pass

    def after_cleanup(self) -> None:
        self.queues.save()
        self.cancel_edit()
        self.clear_text()
        self._queue_cache = ()
        self.render_queue()
        self.render_sessions(time.time())

    def edit_item(self) -> None:
        item_id = self.selected_item_id()
        if not item_id or not self.selected_key or self.busy_now():
            return
        item = self.queues.find(self.selected_key, item_id)
        if item is None:
            return
        self._editing_id = item_id
        self.clear_text()
        self.text_box.insert("1.0", item.text)
        self.text_box.focus_set()
        self.edit_label_var.set(f"Правка: {item.label[:25]}...")
        self.normal_actions.pack_forget()
        self.edit_actions.pack(fill="x", pady=(5, 0))
        self.set_status("IDLE", "Правишь промпт. Ctrl+Enter — сохранить, Esc — отменить.")

    def save_edit(self) -> None:
        if not self._editing_id or not self.selected_key:
            return
        text = self.current_text()
        if not text:
            self.set_status("ERROR", "Пустой текст — правка не сохранена.")
            return
        self.queues.edit(self.selected_key, self._editing_id, text)
        self.queues.save()
        self.cancel_edit()
        self._queue_cache = ()
        self.render_queue()
        self.set_status("IDLE", "Правка сохранена.")

    def cancel_edit(self) -> None:
        self._editing_id = None
        self.edit_actions.pack_forget()
        self.normal_actions.pack(fill="x", pady=(5, 0))
        self.clear_text()
        self.set_status("IDLE", "Правка отменена.")

    # ---- drag reorder -------------------------------------------------
    def on_drag_start(self, event) -> None:
        self._drag_item = self.queue_tree.identify_row(event.y) or None

    def on_drag_motion(self, event) -> None:
        if not self._drag_item:
            return
        target = self.queue_tree.identify_row(event.y)
        if target and target != self._drag_item:
            self.queue_tree.move(self._drag_item, "", self.queue_tree.index(target))

    def on_drag_drop(self, _event) -> None:
        item_id, self._drag_item = self._drag_item, None
        if not item_id or not self.selected_key:
            return
        if not self.queue_tree.exists(item_id):
            return
        if self.queues.move_to(
            self.selected_key, item_id, self.queue_tree.index(item_id)
        ):
            self.queues.save()
            self._queue_cache = ()
            self.render_queue()
            self.queue_tree.selection_set(item_id)

    # ---- sending ------------------------------------------------------
    def _jobs_for(self, keys) -> list:
        jobs = []
        for key in keys:
            session = self.sessions_by_key.get(key)
            if session is None:
                continue
            for item in self.queues.pending(key):
                jobs.append((session, item, session.tab_hint))
        return jobs

    def _sendable_keys(self) -> list:
        return [s.key for s in self.sessions if self.queues.pending(s.key)]

    def send_text_now(self) -> None:
        """Send the box straight away, ahead of the queue.
        
        It still goes through the queue -- that is where item state and the
        failure reason live -- but it jumps to the front and the run starts on
        the spot, ignoring the schedule and the quota wait. This once queued
        the prompt and called a `start_worker_one` that does not exist, so
        nothing was ever sent.
        """
        text = self.current_text()
        if not text:
            self.set_status("ERROR", "Текст пуст. Нечего отправлять.")
            return
        if not self.selected_key:
            self.set_status("ERROR", "Не выбрана сессия.")
            return
        if self.worker.running:
            self.set_status("ERROR", "Отправка уже идёт.")
            return
        session = self.sessions_by_key.get(self.selected_key)
        if session is None:
            self.set_status("ERROR", "Сессия пропала из списка.")
            return
        item = self.queues.add(self.selected_key, text, label=session.name)
        if item is None:
            return
        self.queues.move_to(self.selected_key, item.id, 0)
        self.queues.save()
        self.clear_text()
        self._queue_cache = ()
        self.render_queue()
        self.render_sessions(time.time())
        self._launch([(session, item, session.tab_hint)], immediate=True)

    def send_selected(self) -> None:
        if not self.selected_key:
            self.set_status("ERROR", "Не выбрана сессия.")
            return
        self._launch(self._jobs_for([self.selected_key]), immediate=True)

    def send_all(self) -> None:
        self._launch(self._jobs_for(self._sendable_keys()), immediate=True)

    def send_scheduled(self) -> None:
        when = (self.schedule_var.get() or "").strip()
        try:
            hour, minute = (int(p) for p in when.split(":", 1))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except ValueError:
            self.set_status("ERROR", "Время не читается. Нужен HH:MM.")
            return
        jobs = self._jobs_for(self._sendable_keys())
        if not jobs:
            self.set_status("IDLE", "Очереди пустые.")
            return
        if not messagebox.askyesno(
            APP_NAME,
            f"Отправить {len(jobs)} промпт(ов) в {when}?\n\nОтмена — кнопкой СТОП.",
            parent=self,
        ):
            return
        self._launch(jobs, immediate=False)

    def set_session_time(self) -> None:
        """Give the selected session its own HH:MM instead of the global one.

        Empty clears the override; the session inherits the global time again.
        Only sessions with a pending queue are schedulable -- same surface the
        «По расписанию» button already sends.
        """
        if not self.selected_key:
            self.set_status("ERROR", "Не выбрана сессия.")
            return
        value = (self.session_time_var.get() or "").strip()
        if value:
            try:
                hour, minute = (int(p) for p in value.split(":", 1))
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError
            except ValueError:
                self.set_status("ERROR", "Время не читается. Нужен HH:MM.")
                return
        self.queues.set_schedule(self.selected_key, value)
        self.queues.save()
        self.session_time_var.set(value)
        session = self.sessions_by_key.get(self.selected_key)
        name = session.name if session else self.selected_key
        if value:
            self.set_status("IDLE", f"{name}: своё расписание {value}.")
        else:
            self.set_status("IDLE", f"{name}: наследует общее расписание.")

    def _launch(self, jobs, immediate: bool = False) -> None:
        """Hand a batch to the worker. `immediate` skips schedule and quota.

        The HH:MM field is honoured only by «По расписанию». As a modifier on
        the ordinary send buttons it silently ate every batch for hours.
        """
        if self.worker.running:
            self.set_status("ERROR", "Отправка уже идёт.")
            return
        if not jobs:
            self.set_status("IDLE", "Нечего отправлять.")
            return
        dry = bool(self.dry_var.get())
        self.config_store["schedule_time"] = self.schedule_var.get()
        self.config_store["check_limits"] = self.limits_var.get()
        self.config_store["tray_enabled"] = self.tray_var.get()
        self.config_store.save()

        schedule_time = "" if immediate else self.schedule_var.get()
        check_limits = False if immediate else bool(self.limits_var.get())
        # A session with its own HH:MM fires at its own time; everyone else
        # inherits the global one. The worker splits the batch into segments
        # by effective time, so two sessions can go off in the same night.
        schedules = {}
        for session, _item, _tab in jobs:
            own = self.queues.schedule_of(session.key)
            if own:
                schedules[session.key] = own
        if not dry:
            names = ", ".join(sorted({job[0].name for job in jobs}))
            when = "сейчас" if immediate else (schedule_time or "сейчас")
            extra = f" (своё: {', '.join(sorted(set(schedules.values())))}) " if schedules else " "
            self.log(
                f"Отправляю {len(jobs)} промпт(ов) в: {names}.{extra}Когда: {when}."
            )
        self.set_busy(True)
        item = jobs[0][1]
        if hasattr(item, "id") and hasattr(self, "undo_button"):
            self._undo_item = (jobs[0][0].key, item.id)
            try:
                self.undo_button.pack(
                    side="right", padx=(0, 4), before=self.stop_button
                )
            except tk.TclError:
                pass
        if hasattr(self, "_cancel_undo_timer"):
            self._cancel_undo_timer()
        self.worker.start(
            jobs,
            int(self.config_store["gap_ms"]),
            dry,
            schedule_time=schedule_time,
            check_limits=check_limits,
            schedules=schedules,
        )

    def stop_send(self) -> None:
        self.worker.stop()
        self.set_status("RUNNING", "Останавливаюсь после текущего промпта...")

    def set_busy(self, busy: bool) -> None:
        self.send_text_button.configure(state="disabled" if busy else "normal")
        self.send_queue_button.configure(state="disabled" if busy else "normal")
        self.send_all_button.configure(state="disabled" if busy else "normal")
        self.stop_button.configure(state="normal" if busy else "disabled")

    def run_after_action(self, dry: bool) -> None:
        key = str(self.config_store["after_run"] or afterrun.NOTHING)
        if key == afterrun.NOTHING:
            return
        if dry:
            self.log("Пробный прогон — машину не трогаем.")
            return
        ran, message = afterrun.run_after(key)
        if message:
            self.log(message)
        if not ran:
            self.set_status("ERROR", message)

    # ---- quota --------------------------------------------------------
    def start_limit_scan(self, force: bool = False) -> None:
        if limits is None:
            return
        if self._limit_scanning:
            self._limit_rescan_pending = self._limit_rescan_pending or force
            return
        agents = sorted(self.registry.enabled)
        if not agents:
            return
        if not force and not any(self.limit_monitor.stale(a) for a in agents):
            return
        self._limit_scanning = True

        def work():
            try:
                self.limit_monitor.scan(agents, force=force)
                # Claude writes a structured 429 and no prose, so the text
                # scanner is blind to it. Measured: "limit reached" appears
                # zero times across live transcripts while the account is
                # blocked. This detector reads the record instead.
                if "claude-code" in agents:
                    self.apply_claude_rate_limit()
                overrides = self.config_store["quota_plans"] or {}
                for agent in agents:
                    self.limit_monitor.apply_plan(
                        agent,
                        last_send=self.last_send_for(agent),
                        overrides=overrides,
                    )
                ports = {a: self.deliverer.cdp_status(a) for a in agents}
                self.ui_queue.put(("cdp_status", (ports,)))
            except Exception as exc:
                self.ui_queue.put(("log", (f"Проверка лимитов сорвалась: {exc}",)))
            finally:
                self.ui_queue.put(("limits_done", ()))

        threading.Thread(target=work, name="SAISENT-Limits", daemon=True).start()

    def tick_limits(self) -> None:
        if self.closing:
            return
        self.start_limit_scan()
        self._limit_after = self.after(5000, self.tick_limits)

    def apply_claude_rate_limit(self) -> None:
        """Read Claude's own 429 record and set the quota state from it."""
        from SAISENT_sessions import ratelimit
        from SAISENT_sessions.quota_plan import plan_for

        plan = plan_for("claude-code", self.config_store["quota_plans"] or {})
        window = plan.hours or ratelimit.DEFAULT_WINDOW_HOURS
        try:
            hit = ratelimit.scan_project_dir(
                Path.home() / ".claude" / "projects", window_hours=window
            )
        except Exception as exc:
            self.ui_queue.put(("log", (f"Проба 429 сорвалась: {exc}",)))
            return
        if hit is None:
            self.limit_monitor.set_reading("claude-code", False)
            return
        self.limit_monitor.set_reading("claude-code", True, hit.reset_at(window))

    def activity_snapshot(self) -> dict:
        """key -> last activity, for every session we can currently see.

        Lets a blind send name the chat the text actually reached instead of
        reporting a shrug. Measured: a send aimed at one session landed in
        another, and the old code could only say "unconfirmed".
        """
        try:
            return {s.key: s.last_active for s in self.registry.discover()}
        except Exception as exc:
            self.log(f"Карта активности не читается: {exc}")
            return {}

    def last_send_for(self, agent: str) -> datetime | None:
        """When this agent last received a prompt from us.

        A rolling window -- Claude's five hours -- starts at that moment, not
        at midnight, so the countdown needs it. Queue keys are `agent:id`.
        """
        newest = None
        prefix = f"{agent}:"
        for key, items in self.queues.queues.items():
            if not key.startswith(prefix):
                continue
            for item in items:
                if not item.sent_at:
                    continue
                try:
                    stamp = datetime.fromisoformat(item.sent_at)
                except ValueError:
                    continue
                if newest is None or stamp > newest:
                    newest = stamp
        return newest

    def limit_summary(self) -> str:
        return self.limit_monitor.summary(datetime.now())

    def quota_plan_lines(self) -> list:
        from SAISENT_sessions.quota_plan import plan_for

        overrides = self.config_store["quota_plans"] or {}
        lines = []
        for agent in sorted(self.registry.enabled):
            plan = plan_for(agent, overrides)
            reading = self.limit_monitor.reading(agent)
            state = reading.label(datetime.now()) if reading else "не проверялось"
            lines.append(
                f"{AGENT_LABELS.get(agent, agent)}: {plan.describe()} — {state}"
            )
        return lines

    # ---- «Ещё...» -----------------------------------------------------
    def show_more(self) -> None:
        """Every setting that is not part of sending, in one place."""
        from SAISENT_sessions.deliver import CDP_PROFILES, CDP_RELAUNCH_HINT

        window = tk.Toplevel(self)
        window.title("SAISENT — настройки")
        window.configure(bg=C["background"])
        window.transient(self)

        sched = group(window, " Расписание и лимиты ")
        sched.pack(fill="x", padx=8, pady=(8, 0))
        row = core.vframe(sched)
        row.pack(fill="x")
        core.vlabel(row, text="Отправить в (HH:MM):", small=True).pack(side="left")
        core.ventry(row, textvariable=self.schedule_var, width=7).pack(
            side="left", padx=(4, 8)
        )
        core.vbutton(row, "По расписанию", self.send_scheduled, width=15).pack(
            side="left"
        )
        core.vcheck(
            sched, variable=self.limits_var, text="Ждать сброса лимитов агента"
        ).pack(anchor="w", pady=(4, 0))
        self.limit_more_var = tk.StringVar(value=self.limit_summary())
        core.vlabel(
            sched, textvariable=self.limit_more_var, muted=True, small=True
        ).pack(anchor="w")
        for line in self.quota_plan_lines():
            core.vlabel(sched, text=f"   {line}", muted=True, small=True).pack(
                anchor="w"
            )
        core.vlabel(
            sched,
            text="Правила сброса — ключ \"quota_plans\" в SAISENT.json: "
                 "daily HH:MM, rolling Nh, text.",
            muted=True,
            small=True,
        ).pack(anchor="w", pady=(2, 0))
        core.vbutton(
            sched,
            "Проверить лимиты",
            lambda: (self.start_limit_scan(force=True),
                     self.limit_more_var.set("проверяю...")),
            width=17,
        ).pack(anchor="w", pady=(3, 0))

        machine = group(window, " Машина ")
        machine.pack(fill="x", padx=8, pady=(6, 0))
        row = core.vframe(machine)
        row.pack(fill="x")
        core.vlabel(row, text="После отправки:", small=True).pack(side="left")
        combo = ttk.Combobox(
            row,
            textvariable=self.after_var,
            values=[a.label for a in afterrun.ACTIONS],
            state="readonly",
            width=16,
            style="Vintage.TCombobox",
        )
        combo.pack(side="left", padx=(4, 0))
        self.after_warning_var = tk.StringVar(
            value=afterrun.warning_for(str(self.config_store["after_run"]))
        )
        combo.bind("<<ComboboxSelected>>", self.on_after_action_picked)
        core.vlabel(
            machine, textvariable=self.after_warning_var, muted=True, small=True
        ).pack(anchor="w", pady=(3, 0))
        core.vcheck(
            machine,
            variable=self.tray_var,
            text="Прятать в трей вместо закрытия",
            command=self.remember_flags,
        ).pack(anchor="w")
        core.vcheck(
            machine,
            variable=self.dry_var,
            text="Пробный прогон (ничего не отправляется)",
            command=self.remember_flags,
        ).pack(anchor="w")

        transport = group(window, " Транспорт ")
        transport.pack(fill="both", expand=True, padx=8, pady=(6, 0))
        lines = []
        for agent in sorted(self.registry.enabled):
            port, reason = self._cdp_ports.get(agent) or (0, "не проверялось")
            label = AGENT_LABELS.get(agent, agent)
            if port and agent in CDP_PROFILES:
                lines.append(f"{label}: отладчик на {port} — точно по имени диалога.")
            elif port:
                lines.append(f"{label}: порт {port} живой, селекторы не сняты.")
            else:
                lines.append(f"{label}: {reason} — шлём клавишами, вслепую.")
                hint = CDP_RELAUNCH_HINT.get(agent)
                if hint:
                    lines.append(f"    {hint}")
        info = tk.Text(
            transport,
            height=max(4, min(10, len(lines) + 1)),
            font=FONT_SMALL,
            bg=C["compareBack"],
            fg=C["textPrimary"],
            relief="sunken",
            bd=2,
            wrap="word",
            highlightthickness=0,
        )
        info.insert("1.0", "\n".join(lines) or "Ни один агент не включён.")
        info.configure(state="disabled")
        info.pack(fill="both", expand=True)
        core.vlabel(
            transport,
            text="Отладчик — единственный транспорт, который работает "
                 "при заблокированном экране.",
            muted=True,
            small=True,
        ).pack(anchor="w", pady=(3, 0))

        # T-047: an agent that is running but whose debugger port is dead
        # was launched without the flag -- the hotkey only focuses it. Offer a
        # proper restart (kill + relaunch with the flag), user-confirmed: a
        # restart throws away whatever the agent was in the middle of.
        from SAISENT_sessions.launcher import running_without_debugger

        restart_row = core.vframe(window)
        restart_row.pack(fill="x", padx=8, pady=(0, 4))
        restart_offered = False
        for agent in sorted(self.registry.enabled):
            detected, _exe, _port = running_without_debugger(agent)
            if not detected:
                continue
            restart_offered = True
            core.vbutton(
                restart_row,
                f"Перезапустить {AGENT_LABELS.get(agent, agent)} с отладчиком",
                lambda a=agent: self.restart_with_debugger(a),
                width=34,
                role="danger",
            ).pack(side="left", padx=(0, 4))
        if restart_offered:
            core.vlabel(
                restart_row,
                text="Перезапуск убьёт текущую работу агента!",
                small=True,
                muted=True,
            ).pack(side="left")

        theme_group = group(window, " Тема ")
        theme_group.pack(fill="x", padx=8, pady=(6, 0))
        theme_row = core.vframe(theme_group)
        theme_row.pack(fill="x")
        for name, label in (("vintage", "Vintage Golden"), ("dark", "Тёмная"), ("light", "Светлая")):
            tk.Radiobutton(
                theme_row,
                text=label,
                variable=self.theme_var,
                value=name,
                command=lambda n=name: self.apply_theme(n),
                bg=C["surface"],
                fg=C["textPrimary"],
                selectcolor=C["surfaceAlt"],
                activebackground=C["surfaceRaised"],
                activeforeground=C["textPrimary"],
                font=FONT_SMALL,
                bd=0,
                highlightthickness=0,
            ).pack(side="left", padx=(0, 8))

        row = core.vframe(window)
        row.pack(fill="x", padx=8, pady=8)
        core.vbutton(row, "Включить порты навсегда", self.enable_ports, width=24).pack(
            side="left"
        )
        core.vbutton(row, "Закрыть", window.destroy, width=10).pack(side="right")

    def apply_theme(self, name: str) -> None:
        self.config_store["theme"] = name
        self.config_store.save()
        self.theme_var.set(name)
        if name in core.THEMES:
            C.update(core.THEMES[name])
        self.set_status("IDLE", f"Тема '{name}' применена. Перезапустите окно для полного эффекта.")

    def remember_flags(self) -> None:
        self.config_store["tray_enabled"] = bool(self.tray_var.get())
        self.config_store["dry"] = bool(self.dry_var.get())
        self.config_store["check_limits"] = bool(self.limits_var.get())
        self.config_store.save()

    def on_after_action_picked(self, _event=None) -> None:
        key = afterrun.key_for(self.after_var.get())
        self.config_store["after_run"] = key
        self.config_store.save()
        warning = afterrun.warning_for(key)
        if hasattr(self, "after_warning_var"):
            self.after_warning_var.set(warning)
        if warning:
            self.set_status("ERROR", f"Внимание: {warning}")
        else:
            self.set_status("IDLE", f"После отправки: {afterrun.label_for(key)}.")

    def restart_with_debugger(self, agent: str) -> None:
        """User-confirmed kill + relaunch with the debugger flag (T-047).

        A running agent that never got `--remote-debugging-port` cannot be
        given one later -- the flag is read at launch. The only way to the
        reliable transport is a real restart, and a restart throws away
        whatever the agent was doing, so this is always an explicit confirm,
        never a side effect.
        """
        from SAISENT_sessions.launcher import (
            DEFAULT_PORTS,
            find_executable,
        )
        import subprocess

        label = AGENT_LABELS.get(agent, agent)
        exe = find_executable(agent)
        if not exe:
            self.set_status("ERROR", f"{label}: исполняемый файл не найден.")
            return
        port = int(DEFAULT_PORTS.get(agent) or 0)
        from SAISENT_sessions.launcher import close_gracefully, restart_warning

        if not messagebox.askyesno(
            APP_NAME,
            f"Перезапустить {label} с отладчиком (порт {port})?\n\n"
            f"{restart_warning(agent)}\n\n"
            "Сначала будет обычное закрытие окна, принудительно — только если "
            "не закроется сам. Продолжить?",
            parent=self,
        ):
            self.set_status("IDLE", "Отменено.")
            return
        self.set_status("RUNNING", f"Закрываю {label}...")
        self.update_idletasks()
        # Politely, and only then by force. `taskkill /F` straight away gave
        # the agent no chance to flush, and relaunching before the old process
        # was gone left Electron's single-instance lock holding the app shut.
        exited, message = close_gracefully(os.path.basename(exe))
        self.log(message)
        if not exited:
            self.set_status("ERROR", message)
            return
        self.log(f"Перезапускаю {label} с отладчиком (порт {port}).")
        try:
            subprocess.Popen([exe, f"--remote-debugging-port={port}"], close_fds=True)
        except OSError as exc:
            self.set_status("ERROR", f"{label}: запуск не удался ({exc}).")
            return
        self.set_status("RUNNING", f"{label} перезапускается... Проверь порт {port}.")

    def enable_ports(self) -> None:
        from SAISENT_sessions import launcher

        for agent in sorted(self.registry.enabled):
            if agent in launcher.ARGV_JSON_PATHS:
                _changed, message = launcher.enable_permanent_port(agent)
            else:
                message = f"{AGENT_LABELS.get(agent, agent)}: {launcher.ahk_snippet(agent)}"
            self.log(message)
        self.set_status("IDLE", "Порты прописаны. Подхватятся при перезапуске агента.")

    # ---- plumbing -----------------------------------------------------
    def pump(self) -> None:
        try:
            while True:
                kind, args = self.ui_queue.get_nowait()
                if kind == "status":
                    self.set_status(args[0], args[1])
                elif kind == "log":
                    self.log(args[0])
                elif kind == "cdp_status":
                    self._cdp_ports = dict(args[0])
                elif kind == "limits_done":
                    self._limit_scanning = False
                    if hasattr(self, "limit_more_var"):
                        try:
                            self.limit_more_var.set(self.limit_summary())
                        except tk.TclError:
                            pass
                    if self._limit_rescan_pending:
                        self._limit_rescan_pending = False
                        self.after(0, lambda: self.start_limit_scan(force=True))
                elif kind == "item_state":
                    key, item_id, state, reason, confirmed = args
                    self.queues.mark(key, item_id, state, reason, confirmed=confirmed)
                    self.queues.save()
                    self._queue_cache = ()
                    self.render_queue()
                elif kind == "done":
                    sent, reason = args
                    self.set_busy(False)
                    if (
                        sent > 0
                        and self._undo_item is not None
                        and hasattr(self, "undo_button")
                    ):
                        try:
                            self.undo_button.pack(
                                side="right", padx=(0, 4),
                                before=self.stop_button,
                            )
                        except tk.TclError:
                            pass
                        if hasattr(self, "after"):
                            self._undo_after = self.after(
                                30000, self._hide_undo_button
                            )
                    self.set_status(
                        "DONE" if "остановлено" not in reason else "STOPPED",
                        f"Отправлено {sent}: {reason}",
                    )
                    self._queue_cache = ()
                    self.render_sessions(time.time())
                    self.render_queue()
                    # Only after something actually landed. Blanking the
                    # screen on «Отправлено 0» meant a run that delivered
                    # nothing still killed the display and looked like success.
                    if "остановлено" not in reason and sent > 0:
                        self.run_after_action(bool(self.dry_var.get()))
                    # An overnight batch used to finish silently; a tray
                    # balloon (and a bell when something failed) is the one
                    # announcement the user is awake to hear. Stopped batches
                    # stay silent -- the user stopped them.
                    notice = batch_done_notice(sent, reason)
                    if notice:
                        title, text, warn = notice
                        if warn:
                            self.bell()
                        try:
                            self.tray.balloon(title, text, warn=warn)
                        except Exception:
                            # A balloon is cosmetic; it must never take the
                            # pump down with it.
                            pass
        except queue.Empty:
            pass
        if not self.closing:
            self.after(120, self.pump)

    def set_status(self, state: str, message: str) -> None:
        colors = {
            "IDLE": C["textSecondary"],
            "RUNNING": C["warning"],
            "DONE": C["success"],
            "STOPPED": C["warning"],
            "ERROR": C["danger"],
        }
        self.status_state_var.set(state)
        self.status_var.set(message)
        self.status_state_label.configure(fg=colors.get(state, C["textSecondary"]))
        if state == "ERROR":
            self.log(message)

    def log(self, message: str) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as handle:
                handle.write(f"[{stamp}] {message}\n")
        except OSError:
            pass
        # SAISENT.log grows forever otherwise, and the history panel re-parses
        # the whole file each open. One stat per write; a roll moves the older
        # lines to a dated archive and keeps the tail here, and read_log
        # merges both, so no past run vanishes (T-061).
        try:
            from SAISENT_sessions.history import rotate_log

            rotate_log(LOG_PATH)
        except Exception as exc:
            self.log(f"Ротация журнала не удалась: {exc}")

    def open_log(self) -> None:
        try:
            os.startfile(LOG_PATH)  # noqa: S606 - the user asked for the log
        except OSError as exc:
            self.set_status("ERROR", f"Журнал не открылся: {exc}")

    # ---- templates (T-051) -------------------------------------------
    def rebuild_templates_menu(self) -> None:
        """(Re)build the Шаблоны menu from config. Separator + an entry to
        save the current box as a new template sit under the saved ones."""
        menu = self.templates_menu
        menu.delete(0, "end")
        templates = list(self.config_store["templates"] or [])
        if not templates:
            menu.add_command(label="(шаблонов нет)", state="disabled")
        for index, template in enumerate(templates):
            label = " ".join(template.split())
            if len(label) > 40:
                label = label[:37] + "..."
            menu.add_command(
                label=label,
                command=lambda t=template: self.insert_template(t),
            )
        menu.add_separator()
        menu.add_command(
            label="Сохранить текущий как шаблон...",
            command=self.save_current_as_template,
        )

    def insert_template(self, template: str) -> None:
        """Expand {placeholders} for the selected session and insert at the
        cursor. No session selected -> {session}/{project} stay literal, so a
        template can still be drafted without a pick."""
        session = self.sessions_by_key.get(self.selected_key or "")
        expanded = expand_template(template, session)
        try:
            self.text_box.insert("insert", expanded)
        except tk.TclError:
            self.text_box.insert("end", expanded)
        self.text_box.focus_set()

    def save_current_as_template(self) -> None:
        text = self.current_text()
        if not text:
            self.set_status("IDLE", "Нечего сохранить — поле пустое.")
            return
        templates = list(self.config_store["templates"] or [])
        if text in templates:
            self.set_status("IDLE", "Такой шаблон уже есть.")
            return
        templates.append(text)
        self.config_store["templates"] = templates
        self.config_store.save()
        self.rebuild_templates_menu()
        self.set_status("IDLE", f"Шаблон сохранён ({len(templates)} всего).")

    # ---- send history -------------------------------------------------
    def show_history(self) -> None:
        """Journal of past deliveries, read from SAISENT.log -- no second
        ledger. Groups by run, tallies per verdict, filters by agent and
        session. A session no longer alive shows its last known verdict with
        agent "—"."""
        from SAISENT_sessions.history import (  # noqa: PLC0415 - lazy import
            FAILED,
            SENT,
            SKIPPED,
            UNCONFIRMED,
            VERDICT_LABELS,
            read_log,
        )

        window = tk.Toplevel(self)
        window.title("SAISENT — история отправок")
        window.configure(bg=C["background"])
        window.transient(self)

        # name -> agent for the live registry; dead sessions stay unknown.
        name_agent: dict[str, str] = {}
        for session in self.registry.discover():
            name_agent.setdefault(session.name, session.agent)

        top = core.vframe(window)
        top.pack(fill="x", padx=8, pady=(8, 0))
        agent_var = tk.StringVar(value="Все")
        session_var = tk.StringVar(value="Все")
        tally_var = tk.StringVar(value="")

        core.vlabel(top, text="Агент:", small=True, muted=True).pack(
            side="left"
        )
        agent_combo = ttk.Combobox(
            top,
            textvariable=agent_var,
            values=(),
            state="readonly",
            width=14,
            style="Vintage.TCombobox",
        )
        agent_combo.pack(side="left", padx=(4, 10))
        core.vlabel(top, text="Сессия:", small=True, muted=True).pack(
            side="left"
        )
        session_combo = ttk.Combobox(
            top,
            textvariable=session_var,
            values=(),
            state="readonly",
            width=18,
            style="Vintage.TCombobox",
        )
        session_combo.pack(side="left", padx=(4, 10))
        core.vlabel(top, textvariable=tally_var, small=True, muted=True).pack(
            side="left", expand=True
        )
        core.vbutton(top, "Обновить", lambda: fill(), width=10).pack(
            side="right"
        )

        holder = tk.Frame(window, bg=C["compareBack"], bd=2, relief="sunken")
        holder.pack(fill="both", expand=True, padx=8, pady=6)
        tree = ttk.Treeview(
            holder,
            columns=("when", "session", "verdict", "reason"),
            show="headings",
            selectmode="browse",
            style="Vintage.Treeview",
        )
        for column, title, width, stretch in (
            ("when", "Когда", 130, False),
            ("session", "Сессия", 110, False),
            ("verdict", "Вердикт", 130, False),
            ("reason", "Причина", 420, True),
        ):
            tree.heading(column, text=title)
            tree.column(column, width=width, stretch=stretch, anchor="w")
        for tag, color in (
            (SENT, C["textMuted"]),
            (UNCONFIRMED, C["warning"]),
            (FAILED, C["danger"]),
            (SKIPPED, C["textSecondary"]),
        ):
            tree.tag_configure(tag, foreground=color)
        tree.tag_configure("run", foreground=C["textPrimary"])
        bar = ttk.Scrollbar(
            holder,
            orient="vertical",
            command=tree.yview,
            style="Vintage.Vertical.TScrollbar",
        )
        tree.configure(yscrollcommand=bar.set)
        tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="left", fill="y")

        def fill() -> None:
            runs, loose = read_log(LOG_PATH)
            agent_sel = agent_var.get()
            session_sel = session_var.get()
            agents = ["Все"] + sorted(
                {name_agent.get(d.name, "—") for r in runs for d in r.deliveries}
                | {name_agent.get(d.name, "—") for d in loose}
            )
            sessions = ["Все"] + sorted(
                {d.name for r in runs for d in r.deliveries}
                | {d.name for d in loose}
            )
            agent_combo.configure(values=agents)
            session_combo.configure(values=sessions)
            if agent_sel not in agents:
                agent_var.set("Все")
            if session_sel not in sessions:
                session_var.set("Все")
            agent_sel, session_sel = agent_var.get(), session_var.get()

            def keep(d) -> bool:
                if session_sel != "Все" and d.name != session_sel:
                    return False
                if agent_sel != "Все":
                    actual = name_agent.get(d.name, "—")
                    if actual != agent_sel:
                        return False
                return True

            tree.delete(*tree.get_children())
            counts = {SENT: 0, UNCONFIRMED: 0, FAILED: 0, SKIPPED: 0}
            for run in runs:
                items = [d for d in run.deliveries if keep(d)]
                if not items:
                    continue
                sub = {v: 0 for v in counts}
                for d in items:
                    sub[d.verdict] += 1
                label = (
                    f"{run.at} · {run.count} промпт(ов) в: {run.names} "
                    f"· Когда: {run.when}"
                )
                parent = tree.insert(
                    "", "end", text=label, values=("", "", "", ""),
                    tags=("run",),
                )
                for d in items:
                    counts[d.verdict] += 1
                    tree.insert(
                        parent,
                        "end",
                        values=(
                            d.at,
                            d.name,
                            VERDICT_LABELS[d.verdict],
                            d.reason,
                        ),
                        tags=(d.verdict,),
                    )
            for d in loose:
                if not keep(d):
                    continue
                counts[d.verdict] += 1
                tree.insert(
                    "",
                    "end",
                    values=(d.at, d.name, VERDICT_LABELS[d.verdict], d.reason),
                    tags=(d.verdict,),
                )
            parts = []
            if counts[SENT]:
                parts.append(f"ушло {counts[SENT]}")
            if counts[UNCONFIRMED]:
                parts.append(f"не подтверждено {counts[UNCONFIRMED]}")
            if counts[FAILED]:
                parts.append(f"ошибок {counts[FAILED]}")
            if counts[SKIPPED]:
                parts.append(f"пропущено {counts[SKIPPED]}")
            total = sum(counts.values())
            tally_var.set(f"всего {total}: " + (", ".join(parts) if parts else "пусто"))

        fill()

    # ---- shutdown -----------------------------------------------------
    def _tray_restore(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()

    def _tray_quit(self) -> None:
        self._force_quit = True
        self.on_close()

    def on_close(self) -> None:
        if self.config_store["tray_enabled"] and not self._force_quit:
            self.withdraw()
            self.log("Свёрнут в трей. Работа в фоне продолжается.")
            return
        if self.worker.running and not messagebox.askyesno(
            APP_NAME, "Отправка идёт. Закрыть?", parent=self
        ):
            return
        self.closing = True
        self.worker.stop()
        self.config_store["geometry"] = self.winfo_geometry()
        self.config_store.save()
        self.queues.save()
        try:
            self.tray.stop()
        except Exception:
            pass
        self.destroy()


def acquire_single_instance():
    """Refuse to start twice.

    Two copies both own the queue file, both run the scheduler and both
    deliver: every prompt goes out twice and the queue is whichever process
    wrote last.
    """
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, True, MUTEX_NAME)
    ERROR_ALREADY_EXISTS = 183
    if not handle or kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return None
    return handle


def main() -> None:
    if os.name != "nt":
        raise SystemExit("SAISENT работает только в Windows.")
    guard = acquire_single_instance()
    if guard is None:
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning(
            APP_NAME,
            "SAISENT уже запущен.\n\n"
            "Две копии шлют каждый промпт дважды и затирают очередь друг друга.",
        )
        root.destroy()
        return
    core.set_dpi_awareness()
    # Without its own AppUserModelID a .pyw inherits pythonw's taskbar
    # identity: our icon in the title bar, Python's on the taskbar, and the
    # button grouped with every other Python script.
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Artizem.SAISENT.Console"
        )
    except Exception:
        pass
    SaisentApp().mainloop()


if __name__ == "__main__":
    main()
