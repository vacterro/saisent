"""SAISENT -- send prompts into the agent sessions that are running right now.

The old console asked you to describe the target: an agent name in a combobox,
a glob for an idle probe, a window title fragment, then a hand-built macro of
key presses. All of that was a restatement of things the agents already write
to disk, and none of it could say which chat a keystroke would land in.

This one starts from the sessions. The sidebar lists what is alive, by name,
with its own idle/busy sensor. Each session owns an ordered prompt queue you
can reorder by dragging. Sending resolves the agent's window, selects that
session's tab, pastes the text in one operation and then waits for the
session's own store to move before calling it delivered.

No global hotkeys. No macro steps. Nothing runs unless you press something.
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
from tkinter import messagebox, ttk

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
from SAISENT_sessions.queues import (
    STATE_FAILED,
    STATE_PENDING,
    STATE_SENDING,
    STATE_SENT,
    QueueStore,
)
from SAISENT_sessions import afterrun
from SAISENT_sessions.limitwatch import LimitMonitor

try:
    import SAISENT_watcher.limits as limits
except ImportError:
    limits = None

APP_NAME = "SAISENT"
APP_VERSION = "3.0.0"
HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "SAISENT.json"
QUEUE_PATH = HERE / "SAISENT_QUEUES.json"
LOG_PATH = HERE / "SAISENT.log"


def _load_core():
    """The proven Win32 layer, imported from the legacy console.

    `SAISENT_GUI.pyw` guards its `main()` behind `__name__ == "__main__"`, so
    importing it costs nothing but gives us `WindowsAPI` and the Vintage Golden
    widget helpers instead of a second, subtly different copy of both.
    """
    path = HERE / "SAISENT_core.pyw"
    spec = importlib.util.spec_from_file_location("saisent_gui_core", path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(f"cannot import the Win32 core from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["saisent_gui_core"] = module
    spec.loader.exec_module(module)
    return module


core = _load_core()
C = core.C
FONT = core.FONT
FONT_SMALL = core.FONT_SMALL
FONT_BUTTON = core.FONT_BUTTON

AGENT_LABELS = {
    "claude-code": "Claude Code",
    "freebuff": "Freebuff",
    "antigravity": "Antigravity",
    "codenomad": "CodeNomad",
}

STATE_TEXT = {
    "busy": "занята",
    "idle": "ждёт",
}

ITEM_STATE_TEXT = {
    STATE_PENDING: "в очереди",
    STATE_SENDING: "шлётся",
    STATE_SENT: "ушло",
    STATE_FAILED: "ошибка",
}


# ------------------------------------------------------------------ config
class Config:
    """Small, flat, and written only when something actually changed."""

    defaults = {
        "version": 1,
        "tray_enabled": True,
        "inactive_sessions": [],
        "schedule_time": "",
        "check_limits": True,
        "agents": ["claude-code"],
        "tabs": {},
        "gap_ms": 1500,
        "submit": "ENTER",
        "auto_refresh": False,
        "refresh_seconds": 5,
        "freebuff_roots": [],
        "dry": False,
        "activation_timeout_ms": 10000,
        "key_delay_ms": 45,
        "settle_ms": 400,
        "confirm_seconds": 10,
        "busy_seconds": 20,
        "cdp_titles": {},
        "cdp_profiles": {},
        "after_run": "nothing",
        "geometry": "1000x640",
    }

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = dict(self.defaults)
        self.data["agents"] = list(self.defaults["agents"])
        self.data["tabs"] = {}
        self.data["freebuff_roots"] = []

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        for key, fallback in self.defaults.items():
            value = raw.get(key, fallback)
            if isinstance(fallback, bool) and not isinstance(value, bool):
                continue
            if isinstance(fallback, int) and not isinstance(value, (int, float)):
                continue
            self.data[key] = value
        if not isinstance(self.data.get("tabs"), dict):
            self.data["tabs"] = {}
        if not isinstance(self.data.get("agents"), list):
            self.data["agents"] = ["claude-code"]

    def save(self) -> bool:
        temp = self.path.with_suffix(".json.tmp")
        try:
            temp.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
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
        bordercolor=C["borderDark"],
        lightcolor=C["borderDark"],
        darkcolor=C["borderDark"],
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
    style.map(
        "Vintage.Treeview.Heading",
        background=[("active", C["surfaceAlt"])],
    )
    # Drop the indent column ttk reserves for a tree that has no tree in it.
    style.layout("Vintage.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])


def group(parent: tk.Widget, text: str) -> tk.LabelFrame:
    """A vintage Win95 groupbox (LabelFrame)."""
    return tk.LabelFrame(
        parent,
        text=text,
        font=FONT_SMALL,
        bg=C["surfaceRaised"],
        fg=C["textSecondary"],
        relief="groove",
        bd=2,
        padx=5,
        pady=4,
    )


class ToolTip(object):
    """Vintage tooltip for buttons."""
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tw = None
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.close)

    def enter(self, event=None):
        if not self.text:
            return
        x, y, cx, cy = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 20
        y += self.widget.winfo_rooty() + 20
        self.tw = tk.Toplevel(self.widget)
        self.tw.wm_overrideredirect(True)
        self.tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            self.tw,
            text=self.text,
            justify="left",
            bg=C["compareBack"],
            fg=C["textPrimary"],
            relief="solid",
            borderwidth=1,
            font=FONT_SMALL,
            padx=4,
            pady=2,
        )
        label.pack(ipadx=1, ipady=1)

    def close(self, event=None):
        if self.tw:
            self.tw.destroy()
            self.tw = None


class WrapFrame(tk.Frame):
    """A Frame that wraps its children (flow layout)."""
    def __init__(self, master, **kwargs):
        kwargs.setdefault("bg", C["background"])
        super().__init__(master, **kwargs)
        self.bind("<Configure>", self._on_configure)

    def _on_configure(self, event):
        width = event.width
        x = 0
        y = 0
        max_height = 0
        for child in self.winfo_children():
            cw = child.winfo_reqwidth()
            ch = child.winfo_reqheight()
            if x + cw > width and x > 0:
                x = 0
                y += max_height + 4
                max_height = 0
            child.place(x=x, y=y)
            x += cw + 4
            max_height = max(max_height, ch)
        self.configure(height=y + max_height)


def age_text(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}с"
    if seconds < 3600:
        return f"{seconds // 60}м"
    if seconds < 86400:
        return f"{seconds // 3600}ч"
    return f"{seconds // 86400}д"


# ------------------------------------------------------------- send worker
class SendWorker:
    """Runs a delivery plan on a daemon thread and reports through a queue.

    Everything it touches -- window activation, key presses, the clipboard --
    blocks for hundreds of milliseconds at a time. None of that may happen on
    the Tk thread, which is the whole reason the old console felt like glue.
    """

    def __init__(self, deliverer: Deliverer, report, registry: SessionRegistry = None) -> None:
        self.deliverer = deliverer
        self.report = report
        self.registry = registry
        self.limit_monitor = None
        # "waiting" while parked on a schedule, "sending" once prompts move.
        # The UI uses it to keep the queue editable during the wait.
        self.phase = ""
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def _emit(self, kind: str, *args) -> None:
        """Report one event as a single `(kind, args)` value.

        The callback is whatever the caller already has -- `Queue.put`, a
        `list.append` in a test -- and both take exactly one argument. Passing
        `kind` and the payload as separate positionals is what silently broke
        every test double that used `append`.
        """
        self.report((kind, args))

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self, jobs, gap_ms: int, dry: bool, schedule_time: str = "", check_limits: bool = False) -> bool:
        if self.running:
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(list(jobs), int(gap_ms), bool(dry), schedule_time, check_limits),
            name="SAISENT-Send",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def _wait_for_quota(self, agent: str, sent: int) -> bool:
        """Hold until the agent's quota frees up. False means the run stopped.

        Ticks once a second so the countdown in the status bar actually moves;
        the disk is only touched when the cached reading goes stale, which the
        monitor decides -- including the moment a named reset time arrives.
        """
        monitor = getattr(self, "limit_monitor", None)
        if monitor is None:
            return True
        announced = False
        while True:
            if self._stop.is_set():
                self._emit("done", sent, "остановлено")
                return False
            wall = datetime.now()
            try:
                monitor.scan([agent], now=wall)
            except Exception as exc:
                self._emit("log", f"Проверка лимита {agent} сорвалась: {exc}")
                return True
            reading = monitor.reading(agent)
            if reading is None or not reading.blocking(wall):
                if announced:
                    self._emit("log", f"{agent}: лимит снят, продолжаю.")
                return True
            announced = True
            self._emit(
                "status", "RUNNING", f"Жду сброса лимита — {reading.label(wall)}"
            )
            self._stop.wait(1.0)

    def _run(self, jobs, gap_ms: int, dry: bool, schedule_time: str, check_limits: bool) -> None:
        self.phase = "waiting" if schedule_time else "sending"
        if schedule_time:
            try:
                h, m = map(int, schedule_time.split(':'))
                now = datetime.now()
                target = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if target < now:
                    import datetime as dt_module
                    target += dt_module.timedelta(days=1)
                
                while datetime.now() < target:
                    if self._stop.is_set():
                        self._emit("done", 0, "остановлено")
                        return
                    diff = int((target - datetime.now()).total_seconds())
                    self._emit("status", "RUNNING", f"Ждём расписания {schedule_time} (осталось {diff//60}м {diff%60}с)")
                    self._stop.wait(1.0)
            except Exception:
                pass

        self.phase = "sending"
        sent = 0
        unconfirmed = 0
        try:
            for index, (session, item, tab_index) in enumerate(jobs):
                if self._stop.is_set():
                    self._emit("done", sent, "остановлено")
                    return
                
                if check_limits and not self._wait_for_quota(session.agent, sent):
                    return

                if not dry:
                    # A dry run must leave the row exactly as it found it;
                    # marking it «шлётся» and then never clearing it left the
                    # queue showing a send that never happened.
                    self._emit(
                        "item_state", session.key, item.id, STATE_SENDING, "", False
                    )
                self._emit(
                    "status",
                    "RUNNING",
                    f"{index + 1}/{len(jobs)} -> {session.name}: {item.label[:40]}",
                )
                result = self.deliverer.deliver(session, item.text, tab_index, dry=dry)
                if dry:
                    # Пробный прогон ничего не отправлял — состояние не трогаем.
                    self._emit("log", f"{session.name}: {result}")
                    continue
                if result.ok and result.confirmed:
                    state_val = STATE_SENT
                    reason = result.reason
                elif result.ok:
                    # Клавиши ушли, но стор сессии не двинулся: агент в квоте,
                    # занят или промпт реально не дошёл. Помечать «ушло» было
                    # бы враньём — промпт остаётся в очереди, считаем его
                    # неподтверждённым, а не отправленным.
                    state_val = STATE_PENDING
                    reason = "не подтверждено — агент не показал активности"
                else:
                    state_val = STATE_FAILED
                    reason = result.reason
                confirmed = result.ok and result.confirmed
                # Write the outcome onto the item the caller handed us, not
                # only into a report. The queue pane reads these objects, and
                # a state that exists solely as a message in flight is a state
                # nobody can see if the UI thread is busy.
                item.state = state_val
                item.reason = reason
                item.confirmed = confirmed
                if state_val == STATE_SENT:
                    item.sent_at = datetime.now().isoformat(timespec="seconds")
                self._emit("item_state", session.key, item.id, state_val,
                            reason, confirmed)
                self._emit("log", f"{session.name}: {result}")
                if confirmed:
                    sent += 1
                elif result.ok:
                    unconfirmed += 1
                else:
                    self._emit("done", sent, f"остановлено: {result.reason}")
                    return
                if index + 1 < len(jobs):
                    if gap_ms > 0:
                        wait_until = time.time() + gap_ms / 1000.0
                        while time.time() < wait_until:
                            if self._stop.is_set():
                                self._emit("done", sent, "остановлено")
                                return
                            rem = max(0, wait_until - time.time())
                            self._emit("status", "RUNNING", f"Ждём {rem:.1f}с перед следующим...")
                            self._stop.wait(min(0.2, rem))
                    
                    if self.registry and result.ok and result.confirmed:
                        from SAISENT_sessions.discover import STATE_IDLE
                        while True:
                            if self._stop.is_set():
                                self._emit("done", sent, "остановлено")
                                return
                            sessions = self.registry.discover()
                            current = next((s for s in sessions if s.key == session.key), None)
                            if not current or current.state == STATE_IDLE:
                                break
                            self._emit("status", "RUNNING", f"Ждём ответа {session.name}...")
                            self._stop.wait(1.0)
        except Exception as exc:  # pragma: no cover - defensive
            self._emit("log", f"Сбой отправки: {exc}")
            self._emit("done", sent, f"сбой: {exc}")
            return
        if unconfirmed:
            self._emit("done", sent,
                        f"готово, {unconfirmed} не подтверждено — осталось в очереди")
        else:
            self._emit("done", sent, "готово")


# ---------------------------------------------------------------- the app
def fix_russian_layout_shortcuts(root):
    root.bind('<Control-KeyPress-Cyrillic_es>', lambda e: root.event_generate('<<Copy>>'))
    root.bind('<Control-KeyPress-Cyrillic_ve>', lambda e: root.event_generate('<<Paste>>'))
    root.bind('<Control-KeyPress-Cyrillic_em>', lambda e: root.event_generate('<<Paste>>'))
    root.bind('<Control-KeyPress-Cyrillic_che>', lambda e: root.event_generate('<<Cut>>'))
    root.bind('<Control-KeyPress-Cyrillic_ef>', lambda e: root.event_generate('<<SelectAll>>'))

class SaisentApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.api = core.WindowsAPI()
        self.config_store = Config(CONFIG_PATH)
        self.config_store.load()
        self.queues = QueueStore(QUEUE_PATH)
        self.queues.load()

        self.ui_queue: queue.Queue = queue.Queue()
        self.sessions: list = []
        self.sessions_by_key: dict = {}
        self.selected_key: str | None = None
        self.closing = False
        self._sidebar_cache: dict = {}
        self._queue_cache: tuple = ()
        self._drag_item: str | None = None
        self._auto_after: str | None = None
        # Which queued item the text box is currently rewriting, and whose
        # queue it belongs to -- switching sessions mid-edit must not commit
        # the text into the wrong queue.
        self._editing_id: str | None = None
        self._editing_key: str | None = None

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
        )
        # The registry is what the limit gate reads transcripts through. Left
        # out, `check_limits` was a checkbox wired to nothing.
        self.worker = SendWorker(self.deliverer, self.ui_queue.put, self.registry)
        self.limit_monitor = LimitMonitor(
            self.registry,
            limits.scan_text if limits else (lambda _text: None),
        )
        self.worker.limit_monitor = self.limit_monitor
        self._limit_scanning = False
        self._limit_rescan_pending = False
        self._limit_after: str | None = None
        # agent -> (port, reason). Filled by the off-thread probe; drives the
        # "Адрес" column, which is the only place the user can see whether a
        # prompt will be aimed or merely thrown.
        self._cdp_ports: dict[str, tuple[int, str]] = {}

        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry(str(self.config_store["geometry"]))
        self.minsize(860, 540)
        self.configure(bg=C["background"])
        configure_theme(self)

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(120, self.pump)
        self.refresh_sessions()
        self.apply_auto_refresh()
        self.tick_limits()
        self.tray = core.TrayIcon(
            self.api.user32,
            self.api.kernel32,
            self._tray_restore,
            self._tray_quit,
        )
        self.tray.start("SAISENT")
        fix_russian_layout_shortcuts(self)
        self.log(f"{APP_NAME} {APP_VERSION} запущен.")

    # ---- wiring ------------------------------------------------------
    def _build_cdp_factory(self):
        """Builds one debugger sender per agent from its measured profile.

        The field and the conversation list are different elements in every
        app, so a single shared selector types into nothing the moment a
        second agent shows up. `SAISENT.json` may override any profile key
        under `cdp_profiles.<agent>`.
        """
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

    def _build_registry(self) -> SessionRegistry:
        busy = float(self.config_store["busy_seconds"])
        registry = SessionRegistry(
            providers=[
                ClaudeCodeProvider(busy_seconds=busy),
                FreebuffProvider(
                    roots=list(self.config_store["freebuff_roots"] or []),
                    busy_seconds=busy,
                    running=process_running,
                ),
                AntigravityProvider(busy_seconds=busy),
                CodeNomadProvider(busy_seconds=busy),
            ],
            enabled=set(self.config_store["agents"] or ["claude-code"]),
        )
        return registry

    def activity_of(self, key: str) -> float:
        """Last known write time for a session -- the delivery confirmation."""
        session = self.sessions_by_key.get(key)
        if session is not None:
            fresh = self._rediscover_one(key)
            return fresh if fresh else session.last_active
        return 0.0

    def _rediscover_one(self, key: str) -> float:
        try:
            for session in self.registry.discover():
                if session.key == key:
                    return session.last_active
        except Exception:
            return 0.0
        return 0.0

    # ---- layout ------------------------------------------------------
    def _build_ui(self) -> None:
        root = tk.Frame(self, bg=C["background"])
        root.pack(fill="both", expand=True, padx=6, pady=6)

        self._build_agents_row(root)

        body = ttk.PanedWindow(root, orient="horizontal")
        body.pack(fill="both", expand=True, pady=(6, 0))

        frame_left = tk.Frame(body, bg=C["background"])
        frame_mid = tk.Frame(body, bg=C["background"])
        frame_right = tk.Frame(body, bg=C["background"])

        body.add(frame_left, weight=1)
        body.add(frame_mid, weight=2)
        body.add(frame_right, weight=1)

        self._build_sidebar(frame_left)
        self._build_right(frame_mid)
        self._build_global_queue(frame_right)
        self._build_bottom(root)

    def _build_agents_row(self, parent: tk.Misc) -> None:
        row = group(parent, " Агенты ")
        row.pack(fill="x")

        self.agent_vars: dict[str, tk.BooleanVar] = {}
        for agent in ("claude-code", "freebuff", "antigravity", "codenomad"):
            var = tk.BooleanVar(value=self.registry.is_enabled(agent))
            self.agent_vars[agent] = var
            core.vcheck(
                row,
                variable=var,
                text=AGENT_LABELS[agent],
                command=lambda a=agent: self.toggle_agent(a),
            ).pack(side="left", padx=(0, 14))

        self.agent_note_var = tk.StringVar(value="")
        core.vlabel(
            row, textvariable=self.agent_note_var, muted=True, small=True
        ).pack(side="left", padx=(6, 0))

    def _build_sidebar(self, parent: tk.Misc) -> None:
        side = group(parent, " Живые сессии ")
        side.pack(side="left", fill="both", expand=True)

        bottom_frame = tk.Frame(side, bg=C["background"])
        bottom_frame.pack(side="bottom", fill="x")

        holder = tk.Frame(side, bg=C["compareBack"], bd=2, relief="sunken")
        holder.pack(side="top", fill="both", expand=True)

        self.session_tree = ttk.Treeview(
            holder,
            columns=("send", "name", "agent", "tab", "limit", "state", "project"),
            show="headings",
            selectmode="browse",
            style="Vintage.Treeview",
            height=14,
        )
        for column, title, width, anchor in (
            ("send", "Отпр.", 45, "center"),
            ("name", "Сессия", 150, "w"),
            ("agent", "Агент", 80, "center"),
            ("tab", "Адрес", 74, "center"),
            ("limit", "Лимит", 120, "center"),
            ("state", "Датчик", 74, "w"),
            ("project", "Проект", 130, "w"),
        ):
            self.session_tree.heading(column, text=title)
            self.session_tree.column(column, width=width, anchor=anchor, stretch=False)
        self.session_tree.tag_configure("busy", foreground=C["warning"])
        self.session_tree.tag_configure("idle", foreground=C["textPrimary"])
        self.session_tree.tag_configure("queued", background=C["surface"])
        self.session_tree.pack(side="left", fill="both", expand=True)
        self.session_tree.bind("<<TreeviewSelect>>", self.on_session_selected)
        self.session_tree.bind("<ButtonRelease-1>", self.on_session_click)

        bar = ttk.Scrollbar(
            holder,
            orient="vertical",
            command=self.session_tree.yview,
            style="Vintage.Vertical.TScrollbar",
        )
        bar.pack(side="left", fill="y")
        self.session_tree.configure(yscrollcommand=bar.set)

        controls = core.vframe(bottom_frame)
        controls.pack(fill="x", pady=(5, 0))
        core.vbutton(controls, "Обновить", self.refresh_sessions, width=10).pack(
            side="left"
        )
        self.auto_var = tk.BooleanVar(value=bool(self.config_store["auto_refresh"]))
        core.vcheck(
            controls,
            variable=self.auto_var,
            text=f"каждые {int(self.config_store['refresh_seconds'])} с",
            command=self.apply_auto_refresh,
        ).pack(side="left", padx=(6, 0))

        tabs = core.vframe(bottom_frame)
        tabs.pack(fill="x", pady=(5, 0))
        core.vlabel(tabs, text="Таб выбранной:", small=True).pack(side="left")
        self.tab_var = tk.StringVar(value="")
        core.ventry(tabs, textvariable=self.tab_var, width=3).pack(
            side="left", padx=(4, 4)
        )
        core.vbutton(tabs, "Запомнить", self.remember_tab, width=10).pack(side="left")

        core.vlabel(
            bottom_frame,
            text="0 = не переключать таб",
            muted=True,
            small=True,
        ).pack(fill="x", pady=(3, 0))

        self.sessions_note_var = tk.StringVar(value="")
        core.vlabel(
            bottom_frame, textvariable=self.sessions_note_var, muted=True, small=True
        ).pack(fill="x")

        reply_group = group(bottom_frame, " Последний ответ ")
        reply_group.pack(fill="both", expand=True, pady=(5, 0))
        self.last_reply_box = tk.Text(
            reply_group,
            height=4,
            font=FONT_SMALL,
            bg=C["compareBack"],
            fg=C["textPrimary"],
            relief="sunken",
            bd=2,
            wrap="word",
            state="disabled"
        )
        self.last_reply_box.pack(fill="both", expand=True)

    def _build_right(self, parent: tk.Misc) -> None:
        right = tk.Frame(parent, bg=C["background"])
        right.pack(side="left", fill="both", expand=True, padx=(6, 0))

        text_group = group(right, " Текст ")
        text_group.pack(side="bottom", fill="x", pady=(6, 0))

        self.queue_group = group(right, " Очередь ")
        self.queue_group.pack(side="top", fill="both", expand=True)

        queue_bottom = tk.Frame(self.queue_group, bg=C["background"])
        queue_bottom.pack(side="bottom", fill="x")

        holder = tk.Frame(self.queue_group, bg=C["compareBack"], bd=2, relief="sunken")
        holder.pack(side="top", fill="both", expand=True)

        self.queue_tree = ttk.Treeview(
            holder,
            columns=("num", "state", "text"),
            show="headings",
            selectmode="browse",
            style="Vintage.Treeview",
            height=9,
        )
        for column, title, width, anchor, stretch in (
            ("num", "#", 30, "center", False),
            ("state", "Статус", 80, "w", False),
            ("text", "Промпт", 420, "w", True),
        ):
            self.queue_tree.heading(column, text=title)
            self.queue_tree.column(
                column, width=width, anchor=anchor, stretch=stretch
            )
        self.queue_tree.tag_configure("sent", foreground=C["textMuted"])
        self.queue_tree.tag_configure("failed", foreground=C["danger"])
        self.queue_tree.tag_configure("pending", foreground=C["textPrimary"])
        self.queue_tree.tag_configure("sending", foreground=C["warning"])
        self.queue_tree.pack(side="left", fill="both", expand=True)

        bar = ttk.Scrollbar(
            holder,
            orient="vertical",
            command=self.queue_tree.yview,
            style="Vintage.Vertical.TScrollbar",
        )
        bar.pack(side="left", fill="y")
        self.queue_tree.configure(yscrollcommand=bar.set)

        self.queue_tree.bind("<ButtonPress-1>", self.on_drag_start)
        self.queue_tree.bind("<B1-Motion>", self.on_drag_motion)
        self.queue_tree.bind("<ButtonRelease-1>", self.on_drag_drop)
        self.queue_tree.bind("<Double-Button-1>", self.on_queue_double_click)

        item_row = WrapFrame(queue_bottom)
        item_row.pack(fill="x", pady=(5, 0))
        core.vbutton(item_row, "Выше", lambda: self.move_item(-1), width=6)
        core.vbutton(item_row, "Ниже", lambda: self.move_item(1), width=6)
        core.vbutton(item_row, "Править", self.edit_item, width=8)
        core.vbutton(item_row, "Дублировать", self.duplicate_item, width=11)
        core.vbutton(
            item_row, "Удалить", self.remove_item, width=8, role="danger"
        )

        bulk_row = WrapFrame(queue_bottom)
        bulk_row.pack(fill="x", pady=(3, 0))
        core.vbutton(bulk_row, "Снова в очередь", self.requeue_all, width=15)
        core.vbutton(bulk_row, "Убрать ушедшие", self.clear_finished, width=14)
        core.vbutton(
            bulk_row, "Очистить всё", self.clear_all_queues_ui, width=12, role="danger"
        )
        core.vlabel(
            queue_bottom,
            text="Порядок = порядок отправки. Тащи строку мышью, двойной клик — править.",
            muted=True,
            small=True,
        )

        # Saipen shortcuts
        shortcuts_row = WrapFrame(text_group)
        shortcuts_row.pack(fill="x", pady=(2, 4))
        
        saipen_shortcuts = [
            ("gg", "saipen goal\nGoal Mode pivot / re-authorization"),
            ("hh", "saipen hunt\nAutonomous defect/improvement scan"),
            ("cc", "saipen goal\nSet new objective / resume under goal_mode"),
            ("ccc", "saipen continue + ship\nResume everything, then commit/tag/push"),
            ("ss", "saipen stop\nThe brake: checkpoint, write digest, stop"),
            ("sss", "saipen status\nWhere the run stands, caveman-ded short"),
            ("dd", "saipen plan\nPlanning and adding both (proposal or user items)"),
            ("aa", "saipen markhunt\nDry audit — records to BOARD, never fixes"),
            ("qq", "saipen prepare saiwiki\nPrepare the wiki as a fresh status: ready package"),
            ("qqq", "saipen collect saiwiki + ship\nWiki integration, gates, commit, and push"),
            ("ee", "saipen prepare saitranslate\nPrepare all docs/translations as ready package"),
            ("eee", "saipen collect saitranslate + ship\nTranslation integration, commit, and push"),
            ("pp", "saipen sub spawn saipython\nPython tooling: spawn/maintain/update"),

        ]
        for key, tip in saipen_shortcuts:
            btn = core.vbutton(shortcuts_row, key, width=3, command=lambda k=key: self._insert_shortcut(k))
            ToolTip(btn, tip)

        self.text_box = tk.Text(
            text_group,
            height=6,
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



        actions = WrapFrame(text_group)
        actions.pack(fill="x", pady=(5, 0))
        core.vbutton(actions, "В очередь", self.add_to_queue, width=12)
        core.vbutton(actions, "Отправить щас", self.send_now, width=15)
        core.vbutton(
            actions, "В очередь всем", self.add_to_all_queues, width=15
        )
        # Always present, never appearing: an editing pair that materialises on
        # demand would shift the row under a cursor already moving to it.
        self.save_edit_button = core.vbutton(
            actions, "Сохранить правку", self.save_edit, width=16, state="disabled"
        )
        self.cancel_edit_button = core.vbutton(
            actions, "Отмена", self.cancel_edit, width=8, state="disabled"
        )
        core.vbutton(actions, "Очистить поле", self.clear_text, width=13)

        self.edit_note_var = tk.StringVar(value="Ctrl+Enter — в очередь")
        core.vlabel(
            actions, textvariable=self.edit_note_var, muted=True, small=True
        )
        self.text_box.bind("<Control-Return>", self.on_ctrl_enter)

    def _build_global_queue(self, parent: tk.Misc) -> None:
        glob_q = tk.Frame(parent, bg=C["background"])
        glob_q.pack(side="left", fill="both", expand=True, padx=(6, 0))

        gq_group = group(glob_q, " GLOBAL QUEUE ")
        gq_group.pack(fill="both", expand=True)

        holder = tk.Frame(gq_group, bg=C["compareBack"], bd=2, relief="sunken")
        holder.pack(fill="both", expand=True)

        self.global_queue_tree = ttk.Treeview(
            holder,
            columns=("agent", "project", "text"),
            show="headings",
            selectmode="none",
            style="Vintage.Treeview",
            height=20,
        )
        for column, title, width, anchor, stretch in (
            ("agent", "Агент", 80, "center", False),
            ("project", "Проект", 100, "w", False),
            ("text", "Промпт", 200, "w", True),
        ):
            self.global_queue_tree.heading(column, text=title)
            self.global_queue_tree.column(column, width=width, anchor=anchor, stretch=stretch)
        
        self.global_queue_tree.tag_configure("pending", foreground=C["textPrimary"])
        self.global_queue_tree.tag_configure("sending", foreground=C["warning"])
        
        self.global_queue_tree.pack(side="left", fill="both", expand=True)

        bar = ttk.Scrollbar(
            holder,
            orient="vertical",
            command=self.global_queue_tree.yview,
            style="Vintage.Vertical.TScrollbar",
        )
        bar.pack(side="left", fill="y")
        self.global_queue_tree.configure(yscrollcommand=bar.set)

    def _build_bottom(self, parent: tk.Misc) -> None:
        bottom = group(parent, " Отправка ")
        bottom.pack(fill="x", pady=(6, 0))

        sched_row = core.vframe(bottom)
        sched_row.pack(fill="x", pady=(0, 5))
        
        core.vlabel(sched_row, text="Отправить в (HH:MM):", small=True).pack(side="left")
        self.schedule_var = tk.StringVar(value=str(self.config_store["schedule_time"] or ""))
        core.ventry(sched_row, textvariable=self.schedule_var, width=6).pack(side="left", padx=(4, 14))
        
        self.limits_var = tk.BooleanVar(value=bool(self.config_store["check_limits"]))
        core.vcheck(sched_row, variable=self.limits_var, text="Учитывать лимиты").pack(side="left")
        
        self.tray_var = tk.BooleanVar(value=bool(self.config_store["tray_enabled"]))
        core.vcheck(sched_row, variable=self.tray_var, text="Трей-режим (работа в фоне)").pack(side="left", padx=(12, 0))
        core.vbutton(
            sched_row, "Проверить лимиты", self.scan_limits_now, width=16
        ).pack(side="left", padx=(12, 0))
        core.vbutton(
            sched_row, "Отладчик...", self.show_debugger_help, width=12
        ).pack(side="left", padx=(4, 0))

        # Live countdown. Ticks once a second off the cached reset time, so it
        # costs nothing: the disk is only touched when a reading goes stale.
        self.limit_status_var = tk.StringVar(value="лимиты не проверялись")
        self.limit_status_label = tk.Label(
            sched_row,
            textvariable=self.limit_status_var,
            font=FONT_SMALL,
            bg=C["compareBack"],
            fg=C["textSecondary"],
            relief="sunken",
            bd=2,
            anchor="w",
            padx=4,
        )
        self.limit_status_label.pack(side="left", fill="x", expand=True, padx=(8, 0))

        row = core.vframe(bottom)
        row.pack(fill="x")

        self.send_one_button = core.vbutton(
            row, "ОТПРАВИТЬ ЭТУ ОЧЕРЕДЬ", self.send_selected, role="primary", width=22
        )
        self.send_one_button.pack(side="left")
        self.send_all_button = core.vbutton(
            row, "ОТПРАВИТЬ ВСЕ", self.send_all, width=14
        )
        self.send_all_button.pack(side="left", padx=(4, 0))
        # Scheduling is a separate control on purpose. As a modifier on the
        # normal buttons it silently ate every send for hours.
        self.send_later_button = core.vbutton(
            row, "ПО РАСПИСАНИЮ", self.send_scheduled, width=15
        )
        self.send_later_button.pack(side="left", padx=(4, 0))
        self.stop_button = core.vbutton(
            row, "СТОП", self.stop_send, role="danger", width=7, state="disabled"
        )
        self.stop_button.pack(side="left", padx=(4, 0))

        core.vlabel(row, text="После:", small=True).pack(side="left", padx=(10, 0))
        self.after_var = tk.StringVar(
            value=afterrun.label_for(str(self.config_store["after_run"] or "nothing"))
        )
        after_box = ttk.Combobox(
            row,
            textvariable=self.after_var,
            values=[a.label for a in afterrun.ACTIONS],
            state="readonly",
            width=15,
            style="Vintage.TCombobox",
        )
        after_box.pack(side="left", padx=(4, 0))
        after_box.bind("<<ComboboxSelected>>", self.on_after_action_picked)

        self.dry_var = tk.BooleanVar(value=bool(self.config_store["dry"]))
        core.vcheck(
            row,
            variable=self.dry_var,
            text="Пробный прогон",
            command=self.remember_dry,
        ).pack(side="left", padx=(10, 0))

        core.vbutton(row, "Журнал", self.open_log, width=8).pack(side="right")

        status = core.vframe(bottom)
        status.pack(fill="x", pady=(5, 0))

        self.status_state_var = tk.StringVar(value="IDLE")
        self.status_state_label = tk.Label(
            status,
            textvariable=self.status_state_var,
            font=FONT_SMALL,
            bg=C["surfaceRaised"],
            fg=C["textSecondary"],
            width=9,
            anchor="w",
        )
        self.status_state_label.pack(side="left")

        self.status_var = tk.StringVar(value="Готово.")
        tk.Label(
            status,
            textvariable=self.status_var,
            font=FONT_SMALL,
            bg=C["compareBack"],
            fg=C["textPrimary"],
            relief="sunken",
            bd=2,
            anchor="w",
            padx=4,
        ).pack(side="left", fill="x", expand=True)

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
        # Never refresh over a send in progress: the sidebar the user is
        # watching would rewrite itself under the row that is being delivered.
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
        if not found:
            self.sessions_note_var.set("Ни одной живой сессии.")
        else:
            busy = sum(1 for s in found if s.state == STATE_BUSY)
            self.sessions_note_var.set(f"{len(found)} живых, {busy} заняты")
        self.agent_note_var.set(self.registry.last_error or "")

        if self.selected_key not in self.sessions_by_key:
            self.selected_key = found[0].key if found else None
        self.select_session(self.selected_key)
        self.render_queue()

    def address_label(self, session) -> str:
        """How this prompt will be aimed. Read from cache, never probed here."""
        port = (self._cdp_ports.get(session.agent) or (0, ""))[0]
        if port:
            return f"cdp:{port}"
        if session.tab_hint:
            return f"CTRL+{session.tab_hint}"
        return "вслепую"

    def on_after_action_picked(self, _event=None) -> None:
        """Remember the post-run action, and warn before it can bite.

        Lock and sleep both break later scheduled runs, in different ways.
        Saying so at the moment of choosing is the only place it helps.
        """
        key = afterrun.key_for(self.after_var.get())
        self.config_store["after_run"] = key
        self.config_store.save()
        warning = afterrun.warning_for(key)
        if warning:
            self.set_status("ERROR", f"Внимание: {warning}")
            self.log(f"После отправки выбрано «{afterrun.label_for(key)}» — {warning}")
        else:
            self.set_status("IDLE", f"После отправки: {afterrun.label_for(key)}.")

    def run_after_action(self, dry: bool) -> None:
        """Fire the post-run action once a real batch is finished."""
        key = str(self.config_store["after_run"] or afterrun.NOTHING)
        if key == afterrun.NOTHING:
            return
        if dry:
            self.log("Пробный прогон — экран не гасим, машину не трогаем.")
            return
        ran, message = afterrun.run_after(key)
        if message:
            self.log(message)
        if not ran and message:
            self.set_status("ERROR", message)

    def show_debugger_help(self) -> None:
        """Per-agent debugger state, and the command that turns it on.

        The debugger is the only transport that picks a conversation by name
        and reads the field back, and it is available only when the agent was
        started with the flag -- which keeps getting lost on the next restart.
        SAISENT never relaunches an agent by itself: that would kill whatever
        it is in the middle of.
        """
        from SAISENT_sessions.deliver import CDP_PROFILES, CDP_RELAUNCH_HINT

        window = tk.Toplevel(self)
        window.title("Надёжная отправка")
        window.configure(bg=C["background"])
        window.transient(self)

        body = group(window, " Отладчик по агентам ")
        body.pack(fill="both", expand=True, padx=8, pady=8)

        from SAISENT_sessions.deliver import CDP_PORT_FILES

        lines = []
        for agent in sorted(self.registry.enabled):
            port, reason = self._cdp_ports.get(agent) or (0, "не проверялось")
            label = AGENT_LABELS.get(agent, agent)
            if port and agent in CDP_PROFILES:
                lines.append(f"{label}: порт {port} — точная отправка по имени диалога.")
                continue
            if port:
                # A debugger with no measured selectors: the socket is there,
                # but nothing knows which element is the input field.
                lines.append(
                    f"{label}: порт {port} живой, но селекторы страницы не сняты — "
                    "шлём клавишами."
                )
                continue
            if agent not in CDP_PORT_FILES:
                lines.append(f"{label}: отладчика нет вообще. Только Ctrl+N по табу.")
                continue
            lines.append(f"{label}: {reason}")
            hint = CDP_RELAUNCH_HINT.get(agent)
            if hint:
                lines.append(f"    {hint}")
            if agent not in CDP_PROFILES:
                lines.append(
                    "    (порт поднимется — надо будет снять селекторы страницы)"
                )
        if not lines:
            lines = ["Ни один агент не включён."]

        text = tk.Text(
            body,
            height=max(6, min(18, len(lines) + 2)),
            width=78,
            font=FONT_SMALL,
            bg=C["compareBack"],
            fg=C["textPrimary"],
            relief="sunken",
            bd=2,
            wrap="word",
            highlightthickness=0,
        )
        text.insert("1.0", "\n".join(lines))
        text.configure(state="disabled")
        text.pack(fill="both", expand=True)

        core.vlabel(
            body,
            text="Перезапуск агента убьёт его текущую работу — SAISENT его не трогает.",
            muted=True,
            small=True,
        ).pack(fill="x", pady=(4, 0))

        row = core.vframe(body)
        row.pack(fill="x", pady=(5, 0))
        core.vbutton(
            row,
            "Включить навсегда",
            lambda: self._enable_permanent_ports(text),
            width=18,
            role="primary",
        ).pack(side="left")
        core.vbutton(
            row,
            "Копировать",
            lambda: self._copy_to_clipboard(
                text.get("1.0", "end-1c")
            ),
            width=12,
        ).pack(side="left", padx=(4, 0))
        core.vbutton(row, "Закрыть", window.destroy, width=10).pack(side="right")

    def _enable_permanent_ports(self, text_widget) -> None:
        """Write the debugger port into every agent that supports argv.json.

        This is the only fix that survives the user's own launcher: the flag
        lives in the app's config, so the taskbar icon, the Start menu and an
        AHK `Run(...)` all pick it up. Running agents are left alone -- it
        takes effect the next time they start.
        """
        from SAISENT_sessions import launcher

        results = []
        for agent in sorted(self.registry.enabled):
            if agent not in launcher.ARGV_JSON_PATHS:
                snippet = launcher.ahk_snippet(agent)
                results.append(f"{AGENT_LABELS.get(agent, agent)}: только через запуск")
                results.append(f"    {snippet}")
                continue
            _changed, message = launcher.enable_permanent_port(agent)
            results.append(message)
        if not results:
            results = ["Ни один агент не включён."]
        text_widget.configure(state="normal")
        text_widget.delete("1.0", "end")
        text_widget.insert("1.0", "\n".join(results))
        text_widget.configure(state="disabled")
        for line in results:
            self.log(line)
        self.set_status("IDLE", "Порт отладчика прописан. Нужен перезапуск агента.")

    def _copy_to_clipboard(self, text: str) -> None:
        if Win32Clipboard().set(text):
            self.set_status("IDLE", "Скопировано в буфер обмена.")
        else:
            self.set_status("ERROR", "Буфер обмена занят.")

    # ---- quota -------------------------------------------------------
    def scan_limits_now(self) -> None:
        """Re-read every enabled agent's quota text, off the Tk thread."""
        self.start_limit_scan(force=True)

    def start_limit_scan(self, force: bool = False) -> None:
        if limits is None:
            return
        if self._limit_scanning:
            # Pressing the button during a scan used to do nothing at all.
            # Remember the request and run it the moment the current one ends.
            self._limit_rescan_pending = self._limit_rescan_pending or force
            return
        agents = sorted(self.registry.enabled)
        if not agents:
            return
        if not force and not any(self.limit_monitor.stale(a) for a in agents):
            return
        self._limit_scanning = True
        self.limit_status_var.set("проверяю лимиты...")

        def work():
            try:
                self.limit_monitor.scan(agents, force=force)
            except Exception as exc:
                self.ui_queue.put(("log", (f"Проверка лимитов сорвалась: {exc}",)))
            try:
                # The debugger probe opens a socket. Same thread as the limit
                # scan on purpose: neither belongs anywhere near the Tk loop.
                ports = {a: self.deliverer.cdp_status(a) for a in agents}
                self.ui_queue.put(("cdp_status", (ports,)))
            except Exception as exc:
                self.ui_queue.put(("log", (f"Проба отладчика сорвалась: {exc}",)))
            finally:
                self.ui_queue.put(("limits_done", ()))

        threading.Thread(target=work, name="SAISENT-Limits", daemon=True).start()

    def tick_limits(self) -> None:
        """One second of countdown, from cache. No disk, no rescan."""
        if self.closing:
            return
        wall = datetime.now()
        self.limit_status_var.set(self.limit_monitor.summary(wall))
        blocked = bool(self.limit_monitor.blocking_agents(wall))
        self.limit_status_label.configure(
            fg=C["danger"] if blocked else C["textSecondary"]
        )
        # A reading only goes stale on its own schedule; this is what makes the
        # panel pick the reset up by itself the second it lands.
        self.start_limit_scan()
        self._limit_after = self.after(1000, self.tick_limits)

    def render_sessions(self, now: float) -> None:
        tree = self.session_tree
        wanted = []
        inactive = set(self.config_store["inactive_sessions"] or [])
        
        # Read the cache, never the disk: scanning transcripts here meant
        # opening twenty files on the Tk thread every single refresh.
        wall = datetime.now()

        for session in self.sessions:
            pending = len(self.queues.pending(session.key))
            mark = "☐" if session.key in inactive else "☑"

            reading = self.limit_monitor.reading(session.agent)
            limit_str = "?" if reading is None else reading.label(wall)
            address = self.address_label(session)
            values = (
                mark,
                session.name,
                session.agent,
                address,
                limit_str,
                f"{STATE_TEXT.get(session.state, session.state)} {age_text(session.age_seconds(now))}",
                session.project_name,
            )
            tags = [session.state]
            if pending:
                tags.append("queued")
                values = (mark, f"{session.name}  [{pending}]",) + values[2:]
            wanted.append((session.key, values, tuple(tags)))

        # Rewrite only what changed: a full delete/insert loses the selection
        # and makes the list flicker on every refresh.
        current = list(tree.get_children(""))
        if [key for key, _v, _t in wanted] != current:
            tree.delete(*current)
            for key, values, tags in wanted:
                tree.insert("", "end", iid=key, values=values, tags=tags)
            self._sidebar_cache = {key: (values, tags) for key, values, tags in wanted}
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
        self.tab_var.set("" if session is None else str(session.tab_hint or 0))
        title = f" Очередь — {session.name} " if session else " Очередь "
        self.queue_group.configure(text=title)

    def on_session_selected(self, _event=None) -> None:
        selection = self.session_tree.selection()
        if not selection:
            return
        # An edit belongs to the queue it came from. Carrying it across would
        # commit one session's text into another's list.
        if self._editing_key and self._editing_key != selection[0]:
            self.cancel_edit()
        self.selected_key = selection[0]
        session = self.sessions_by_key.get(self.selected_key)
        self.tab_var.set("" if session is None else str(session.tab_hint or 0))
        self.queue_group.configure(
            text=f" Очередь — {session.name} " if session else " Очередь "
        )

        self.last_reply_box.configure(state="normal")
        self.last_reply_box.delete("1.0", "end")
        if session and hasattr(session, "last_reply") and session.last_reply:
            self.last_reply_box.insert("1.0", session.last_reply)
        self.last_reply_box.configure(state="disabled")

        self.render_queue()

    def on_session_click(self, event) -> None:
        region = self.session_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        column = self.session_tree.identify_column(event.x)
        if column == "#1":
            row_id = self.session_tree.identify_row(event.y)
            if row_id:
                inactive = set(self.config_store["inactive_sessions"] or [])
                if row_id in inactive:
                    inactive.discard(row_id)
                else:
                    inactive.add(row_id)
                self.config_store["inactive_sessions"] = list(inactive)
                self.config_store.save()
                self._sidebar_cache.pop(row_id, None)
                self.render_sessions(time.time())

    def remember_tab(self) -> None:
        if not self.selected_key:
            return
        try:
            value = int(self.tab_var.get() or 0)
        except ValueError:
            self.set_status("ERROR", "Таб — это число 0..9.")
            return
        if not 0 <= value <= 9:
            self.set_status("ERROR", "Таб — это число 0..9.")
            return
        tabs = dict(self.config_store["tabs"] or {})
        if value:
            tabs[self.selected_key] = value
        else:
            tabs.pop(self.selected_key, None)
        self.config_store["tabs"] = tabs
        self.config_store.save()
        session = self.sessions_by_key.get(self.selected_key)
        if session is not None:
            session.tab_hint = value or None
        self.render_sessions(time.time())
        self.set_status("IDLE", f"Таб запомнен: {value or 'не переключать'}.")

    # ---- queue -------------------------------------------------------
    def render_queue(self) -> None:
        tree = self.queue_tree
        key = self.selected_key or ""
        items = self.queues.items(key)
        snapshot = tuple(
            (item.id, item.state, item.label, item.reason) for item in items
        )
        if snapshot == self._queue_cache:
            return
        self._queue_cache = snapshot
        selected = tree.selection()
        tree.delete(*tree.get_children(""))
        for index, item in enumerate(items, start=1):
            label = item.label
            if item.state == STATE_FAILED and item.reason:
                label = f"{label}   << {item.reason}"
            elif item.state == STATE_PENDING and item.reason:
                # Неподтверждённая доставка осталась в очереди: reason
                # объясняет, почему «ушло» не поставлено.
                label = f"{label}   << {item.reason}"
            tree.insert(
                "",
                "end",
                iid=item.id,
                values=(index, ITEM_STATE_TEXT.get(item.state, item.state), label),
                tags=(item.state,),
            )
        if selected and tree.exists(selected[0]):
            tree.selection_set(selected[0])
        self.render_global_queue()

    def render_global_queue(self) -> None:
        if not hasattr(self, "global_queue_tree"):
            return
        
        tree = self.global_queue_tree
        tree.delete(*tree.get_children(""))
        
        all_items = []
        for session in self.sessions:
            items = self.queues.items(session.key)
            for item in items:
                if item.state in (STATE_PENDING, STATE_SENDING):
                    all_items.append((session, item))
                    
        for session, item in all_items:
            tree.insert(
                "",
                "end",
                values=(session.agent, session.project_name or session.name, item.label),
                tags=(item.state,)
            )

    def on_ctrl_enter(self, _event) -> str:
        # One meaning in both modes: commit whatever the box holds. Which
        # commit it is stays written in the note beside the buttons.
        if self._editing_id:
            self.save_edit()
        else:
            self.add_to_queue()
        return "break"

    def busy_now(self) -> bool:
        """Refuse queue surgery only while prompts are actually going out.

        A worker parked on a schedule is not sending anything, and locking the
        queue for the hours it waits produced a log made of nothing but
        «Идёт отправка — очередь сейчас не трогаем».
        """
        if self.worker.running and getattr(self.worker, "phase", "") != "waiting":
            self.set_status("ERROR", "Идёт отправка — очередь сейчас не трогаем.")
            return True
        return False

    def current_text(self) -> str:
        return self.text_box.get("1.0", "end-1c").strip()

    def send_now(self) -> None:
        """Send what is in the box, to the selected session, right now.

        It still goes through the queue -- that is where item state, the
        read-back result and the failure reason live -- but it jumps to the
        front and the run starts on the spot, ignoring the schedule and the
        quota wait. Previously this queued the prompt and then called a
        `start_worker_one` that does not exist, so the send never happened and
        the text just piled up in the list.
        """
        text = self.current_text()
        if not text:
            self.set_status("ERROR", "Поле текста пустое.")
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
            self.set_status("ERROR", "Промпт не принят.")
            return
        # Ahead of whatever was already waiting: "now" outranks the backlog.
        self.queues.move_to(self.selected_key, item.id, 0)
        self.queues.save()
        if self._editing_id:
            self.cancel_edit()
        self.clear_text()
        self._queue_cache = ()
        self.render_queue()
        self.render_sessions(time.time())
        self._launch([(session, item, session.tab_hint)], immediate=True)

    def add_to_queue(self) -> None:
        text = self.current_text()
        if not text:
            self.set_status("ERROR", "Поле текста пустое.")
            return
        if not self.selected_key:
            self.set_status("ERROR", "Не выбрана сессия.")
            return
        session = self.sessions_by_key.get(self.selected_key)
        self.queues.add(self.selected_key, text, label=session.name if session else "")
        self.queues.save()
        if self._editing_id:
            # Adding consumes the box, so the edit it was holding is over.
            self.cancel_edit()
        self.clear_text()
        self.render_queue()
        self.render_sessions(time.time())
        self.set_status("IDLE", f"В очередь: {session.name if session else ''}.")

    def add_to_all_queues(self) -> None:
        text = self.current_text()
        if not text:
            self.set_status("ERROR", "Поле текста пустое.")
            return
        if not self.sessions:
            self.set_status("ERROR", "Живых сессий нет.")
            return
        for session in self.sessions:
            self.queues.add(session.key, text, label=session.name)
        self.queues.save()
        if self._editing_id:
            self.cancel_edit()
        self.clear_text()
        self.render_queue()
        self.render_sessions(time.time())
        self.set_status("IDLE", f"В очередь ко всем: {len(self.sessions)}.")

    def clear_text(self) -> None:
        self.text_box.delete("1.0", "end")

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
            self.render_queue()
            self.render_sessions(time.time())

    # ---- editing a queued prompt --------------------------------------
    def on_queue_double_click(self, _event) -> str:
        self.edit_item()
        return "break"

    def edit_item(self) -> None:
        """Modal editor for queue items."""
        item_id = self.selected_item_id()
        if not item_id or not self.selected_key or self.busy_now():
            return
        item = self.queues.find(self.selected_key, item_id)
        if item is None:
            return
            
        dialog = tk.Toplevel(self)
        dialog.title("Редактор промпта")
        dialog.geometry("500x300")
        dialog.transient(self)
        dialog.grab_set()
        
        configure_theme(dialog)
        dialog.configure(bg=C["background"])
        
        text = tk.Text(
            dialog,
            wrap="word",
            bg=C["backgroundSoft"],
            fg=C["textPrimary"],
            insertbackground=C["textPrimary"],
            font=("Verdana", 10),
            bd=1,
            relief="solid",
        )
        text.pack(fill="both", expand=True, padx=10, pady=10)
        text.insert("1.0", item.text)
        
        # Add local fix for Russian layout inside modal
        fix_russian_layout_shortcuts(text)
        
        btn_frame = tk.Frame(dialog, bg=C["background"])
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))
        
        def save():
            new_text = text.get("1.0", "end-1c").strip()
            if new_text and new_text != item.text:
                if self.queues.edit_text(self.selected_key, item_id, new_text):
                    self.queues.save()
                    self._queue_cache = ()
                    self.render_queue()
                    self.log(f"Изменён промпт: {new_text[:30]}...")
            dialog.destroy()
            
        save_btn = tk.Button(
            btn_frame, 
            text="Сохранить (Ctrl+Enter)", 
            command=save,
            bg=C["surfaceRaised"],
            fg=C["textPrimary"],
            font=FONT_BUTTON,
            relief="raised",
            bd=1
        )
        save_btn.pack(side="right")
        
        text.bind("<Control-Return>", lambda e: save())
        text.focus_set()

    def save_edit(self) -> None:
        if not self._editing_id or not self._editing_key:
            return
        text = self.current_text()
        if not text:
            self.set_status("ERROR", "Пустой текст — правка не сохранена.")
            return
        changed = self.queues.edit(self._editing_key, self._editing_id, text)
        item_id, key = self._editing_id, self._editing_key
        self.queues.save()
        self.cancel_edit()
        self._queue_cache = ()
        self.render_queue()
        self.render_sessions(time.time())
        if key == self.selected_key and self.queue_tree.exists(item_id):
            self.queue_tree.selection_set(item_id)
        self.set_status(
            "IDLE", "Правка сохранена." if changed else "Текст не изменился."
        )

    def cancel_edit(self) -> None:
        self._editing_id = None
        self._editing_key = None
        self.clear_text()
        self.save_edit_button.configure(state="disabled")
        self.cancel_edit_button.configure(state="disabled")
        self.edit_note_var.set("Ctrl+Enter — в очередь")

    def duplicate_item(self) -> None:
        item_id = self.selected_item_id()
        if not item_id or not self.selected_key or self.busy_now():
            return
        clone = self.queues.duplicate(self.selected_key, item_id)
        if clone is None:
            return
        self.queues.save()
        self._queue_cache = ()
        self.render_queue()
        self.render_sessions(time.time())
        self.queue_tree.selection_set(clone.id)
        self.set_status("IDLE", "Дубликат добавлен следом.")

    def requeue_all(self) -> None:
        if not self.selected_key or self.busy_now():
            return
        count = self.queues.requeue_all(self.selected_key)
        self.queues.save()
        self.render_queue()
        self.render_sessions(time.time())
        self.set_status("IDLE", f"Снова в очередь: {count}.")

    def clear_finished(self) -> None:
        if not self.selected_key or self.busy_now():
            return
        count = self.queues.clear_finished(self.selected_key)
        self.queues.save()
        self.render_queue()
        self.set_status("IDLE", f"Убрано ушедших: {count}.")

    def clear_all_queues_ui(self) -> None:
        if self.busy_now():
            return
        if not messagebox.askyesno("SAISENT", "Удалить все промпты из всех сессий?", parent=self):
            return
        count = self.queues.clear_all_queues()
        self.queues.save()
        self.render_queue()
        self.render_sessions(time.time())
        self.set_status("IDLE", f"Очищено {count} промптов во всех сессиях.")

    def _insert_shortcut(self, key: str) -> None:
        text = self.text_box.get("1.0", "end-1c")
        if text and not text.endswith("\n"):
            self.text_box.insert("end", "\n" + key)
        else:
            self.text_box.insert("end", key)
        self.text_box.focus_set()

    # ---- drag reorder -------------------------------------------------
    def on_drag_start(self, event) -> None:
        self._drag_item = self.queue_tree.identify_row(event.y) or None

    def on_drag_motion(self, event) -> None:
        if not self._drag_item:
            return
        target = self.queue_tree.identify_row(event.y)
        if not target or target == self._drag_item:
            return
        position = self.queue_tree.index(target)
        self.queue_tree.move(self._drag_item, "", position)

    def on_drag_drop(self, _event) -> None:
        item_id, self._drag_item = self._drag_item, None
        if not item_id or not self.selected_key:
            return
        if not self.queue_tree.exists(item_id):
            return
        position = self.queue_tree.index(item_id)
        if self.queues.move_to(self.selected_key, item_id, position):
            self.queues.save()
            # The cache is stale by construction after a drag: the tree already
            # holds the new order, so force the numbering column to catch up.
            self._queue_cache = ()
            self.render_queue()
            self.queue_tree.selection_set(item_id)

    # ---- sending ------------------------------------------------------
    def remember_dry(self) -> None:
        self.config_store["dry"] = bool(self.dry_var.get())
        self.config_store.save()

    def _jobs_for(self, keys) -> list:
        jobs = []
        for key in keys:
            session = self.sessions_by_key.get(key)
            if session is None:
                continue
            for item in self.queues.pending(key):
                jobs.append((session, item, session.tab_hint))
        return jobs

    def send_selected(self) -> None:
        """Send now. The «Отправить в (HH:MM)» field does NOT apply here.

        It used to: a stale `3:01` left in that box turned every press of
        ОТПРАВИТЬ into a silent four-hour wait, and the log filled with
        `Когда: 3:01` for batches the user believed had gone out. A field
        nobody re-read must never change what a button does -- scheduling now
        has its own button, and it says so.
        """
        if not self.selected_key:
            self.set_status("ERROR", "Не выбрана сессия.")
            return
        self._launch(self._jobs_for([self.selected_key]), immediate=True)

    def send_all(self) -> None:
        self._launch(self._jobs_for(self._sendable_keys()), immediate=True)

    def _sendable_keys(self) -> list:
        inactive = set(self.config_store["inactive_sessions"] or [])
        return [
            s.key
            for s in self.sessions
            if s.key not in inactive and self.queues.pending(s.key)
        ]

    def send_scheduled(self) -> None:
        """The only path that honours «Отправить в (HH:MM)»."""
        when = (self.schedule_var.get() or "").strip()
        if not when:
            self.set_status("ERROR", "Пустое время — впиши HH:MM или жми ОТПРАВИТЬ.")
            return
        try:
            hour, minute = (int(part) for part in when.split(":", 1))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except ValueError:
            self.set_status("ERROR", f"Время {when!r} не читается. Нужен HH:MM.")
            return
        jobs = self._jobs_for(self._sendable_keys())
        if not jobs:
            self.set_status("IDLE", "Нечего планировать — очереди пустые.")
            return
        if not messagebox.askyesno(
            "SAISENT",
            f"Отправить {len(jobs)} промпт(ов) в {when}?\n\n"
            "До этого времени SAISENT будет ждать. Отмена — кнопкой СТОП.",
            parent=self,
        ):
            return
        self._launch(jobs, immediate=False)

    def _launch(self, jobs, immediate: bool = False) -> None:
        """Hand a batch to the worker. `immediate` means the word "щас".

        A scheduled run waits for the clock and, if asked, for the quota to
        clear. Neither applies to a button labelled "now": a manual override
        that silently sits until 02:28 is a button lying about its own name.
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

        if not dry:
            names = ", ".join(sorted({job[0].name for job in jobs}))
            when = "сейчас" if immediate else (schedule_time or "сейчас")
            self.log(f"Отправляю {len(jobs)} промпт(ов) в: {names}. Когда: {when}.")
        self.set_busy(True)
        self.worker.start(
            jobs,
            int(self.config_store["gap_ms"]),
            dry,
            schedule_time=schedule_time,
            check_limits=check_limits,
        )

    def stop_send(self) -> None:
        self.worker.stop()
        self.set_status("RUNNING", "Останавливаюсь после текущего промпта...")

    def set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.send_one_button.configure(state=state)
        self.send_all_button.configure(state=state)
        self.stop_button.configure(state="normal" if busy else "disabled")

    # ---- reporting ----------------------------------------------------
    def report(self, kind: str, *args) -> None:
        self.ui_queue.put((kind, args))

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
                    self._sidebar_cache = {}
                elif kind == "limits_done":
                    self._limit_scanning = False
                    if self._limit_rescan_pending:
                        self._limit_rescan_pending = False
                        self.after(0, lambda: self.start_limit_scan(force=True))
                    self.limit_status_var.set(
                        self.limit_monitor.summary(datetime.now())
                    )
                    self._sidebar_cache = {}
                    self.render_sessions(time.time())
                elif kind == "item_state":
                    key, item_id, state, reason, confirmed = args
                    self.queues.mark(key, item_id, state, reason,
                                     confirmed=confirmed)
                    self.queues.save()
                    if key == self.selected_key:
                        self.render_queue()
                elif kind == "done":
                    sent, reason = args
                    self.set_busy(False)
                    self.set_status(
                        "DONE" if "остановлено" not in reason else "STOPPED",
                        f"Отправлено {sent}: {reason}",
                    )
                    self.render_sessions(time.time())
                    self.render_queue()
                    # Only after a run that actually finished on its own. A
                    # batch the user stopped means they are at the machine.
                    if "остановлено" not in reason:
                        self.run_after_action(bool(self.dry_var.get()))
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

    def open_log(self) -> None:
        try:
            os.startfile(LOG_PATH)  # noqa: S606 - the user asked for the log
        except OSError as exc:
            self.set_status("ERROR", f"Журнал не открылся: {exc}")

    # ---- shutdown -----------------------------------------------------
    def _tray_restore(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()

    def _tray_quit(self) -> None:
        self._force_quit = True
        self.on_close()

    def on_close(self) -> None:
        if self.config_store["tray_enabled"] and not getattr(self, "_force_quit", False):
            self.withdraw()
            self.log("Свёрнут в трей. Работа в фоне продолжается.")
            return
        if self.worker.running:
            if not messagebox.askyesno(
                APP_NAME, "Остановить выполнение и закрыть?", parent=self
            ):
                return
        self.worker.stop()
        self.tray.stop()
        self.destroy()


MUTEX_NAME = "Local\\SAISENT_SESSIONS_CONSOLE_SINGLE_INSTANCE"


def acquire_single_instance():
    """Refuse to start twice.

    Two copies both hold `SAISENT_QUEUES.json`, both run the scheduler and
    both deliver: every prompt goes out twice and the queue file is whichever
    process wrote last. Returns the handle (kept alive for the process) or
    None when another copy already owns it.
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
        from tkinter import messagebox as mb

        root = tk.Tk()
        root.withdraw()
        mb.showwarning(
            APP_NAME,
            "SAISENT уже запущен.\n\n"
            "Две копии шлют каждый промпт дважды и затирают очередь друг друга.",
        )
        root.destroy()
        return
    core.set_dpi_awareness()
    SaisentApp().mainloop()


if __name__ == "__main__":
    main()
