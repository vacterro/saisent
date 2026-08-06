"""T-4: расписание уважает лимит-гейт агента.

`_repeat_tick` должен пропускать срабатывание, когда watcher-гейт держит
отправку («limit reached»), и НЕ двигать цепочку next_run — чтобы после
сброса лимита тик запустил последовательность сам, не потеряв запланированный
запуск и не удвоив его.
"""

import os
import sqlite3
import tempfile
import time
from types import SimpleNamespace

import pytest

import SAISENT_GUI as G


class FakeRunner:
    def __init__(self):
        self.running = False
        self.starts = []

    def start(self, config, reason):
        self.starts.append(reason)
        return True


def make_app(watcher=None, *, next_run=None, interval_hours=5,
             schedule_enabled=True, repeat_enabled=True):
    """SAISENTApp-заглушка без tk: __new__ без __init__, только поля,
    что читает _repeat_tick. Методы разрешаются через класс."""
    config = G.AppConfig(
        schedule_enabled=schedule_enabled,
        repeat_enabled=repeat_enabled,
        interval_hours=interval_hours,
        next_run=next_run or "",
    )
    app = object.__new__(G.SAISENTApp)
    app.config = config
    app.saved_config = config
    app.closing = False
    app.runner = FakeRunner()
    app.watcher = watcher
    app._scheduled_fire_base = None
    app._pending_fire = False
    app._limit_gate_was_active = False
    app.log = lambda *a, **k: None
    app.update_summaries = lambda: None
    app._write_schedule_date = lambda: None
    app.first_tick = True
    return app


class FakeWatcher:
    """limit_active читается планировщиком из UI-потока."""

    def __init__(self, active: bool):
        self._active = active

    def limit_active(self):
        return self._active


def past_iso(hours_ago=1):
    from datetime import datetime, timedelta
    return (datetime.now() - timedelta(hours=hours_ago)).isoformat(
        timespec="seconds")


# --------------------------------------------------------------- limit_active
def make_sqlite_store(dirpath, text, now_minus=60):
    db = os.path.join(dirpath, "store.db")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, text TEXT, "
                 "created_at INTEGER)")
    conn.execute(
        "INSERT INTO messages (text, created_at) VALUES (?, ?)",
        (text, int(time.time()) - now_minus))
    conn.commit()
    conn.close()
    return db


class NoopAPI:
    def resolve_target(self, *a):
        return SimpleNamespace(hwnd=1, title="T")

    def activate_window(self, *a):
        return True

    def is_foreground(self, *a):
        return True

    def send_text(self, *a):
        pass

    def send_combo(self, *a):
        pass


def make_controller(dirpath, store_text=None, limit_enabled=True):
    wc = G.WatcherController(
        api=NoopAPI(),
        on_log=lambda *a, **k: None,
        on_status=lambda *a, **k: None,
        state_path=os.path.join(dirpath, "s.json"),
    )
    wc.limit_enabled = limit_enabled
    if store_text is not None:
        db = make_sqlite_store(dirpath, store_text)
        wc.set_probe("sqlite", db, 0, "wal_mtime", "messages")
    return wc


def test_limit_active_blocks_when_store_says_limit_reached():
    with tempfile.TemporaryDirectory() as d:
        wc = make_controller(d, "Daily free limit reached. Resets at 23:59")
        assert wc.limit_active() is True


def test_limit_active_clear_when_store_clean():
    with tempfile.TemporaryDirectory() as d:
        wc = make_controller(d, "Just a normal reply from the agent")
        assert wc.limit_active() is False


def test_limit_active_disabled_never_blocks():
    with tempfile.TemporaryDirectory() as d:
        wc = make_controller(d, "Daily free limit reached", limit_enabled=False)
        assert wc.limit_active() is False


def test_limit_active_no_probe_no_block():
    with tempfile.TemporaryDirectory() as d:
        wc = make_controller(d, store_text=None)
        assert wc.limit_active() is False


def test_limit_active_holds_until_resets_at():
    from datetime import datetime, timedelta
    with tempfile.TemporaryDirectory() as d:
        wc = make_controller(d, "Daily free limit reached. Resets at 23:59")
        assert wc.limit_active() is True
        # имитируем проход окна: resets_at уже прошёл
        wc._limit_until = datetime.now() - timedelta(minutes=1)
        wc._limit_grace_until = None
        assert wc.limit_active() is False


# ------------------------------------------------------------ _repeat_tick
def test_repeat_tick_skips_and_keeps_chain_when_limit_active():
    past = past_iso(hours_ago=1)
    app = make_app(
        watcher=FakeWatcher(active=True),
        next_run=past,
    )
    now = G.datetime.now()
    app._repeat_tick(app.saved_config, now)
    # Ничего не запущено
    assert app.runner.starts == []
    # Цепочка НЕ сдвинута: next_run остался в прошлом
    assert app.saved_config.next_run == past
    # Флаг «лимит был активен» запомнен
    assert app._limit_gate_was_active is True


def test_repeat_tick_fires_after_limit_passes():
    app = make_app(
        watcher=FakeWatcher(active=False),
        next_run=past_iso(hours_ago=1),
    )
    now = G.datetime.now()
    app._repeat_tick(app.saved_config, now)
    assert app.runner.starts == ["schedule"]
    # Цепочка сдвинута вперёд на интервал
    nxt = G.parse_iso_time(app.saved_config.next_run)
    assert nxt is not None and nxt > now
    assert app._scheduled_fire_base is now


def test_repeat_tick_no_watcher_no_gate():
    app = make_app(watcher=None, next_run=past_iso(hours_ago=1))
    app._repeat_tick(app.saved_config, G.datetime.now())
    assert app.runner.starts == ["schedule"]


def test_repeat_tick_limit_then_reset_fires_second_tick():
    """Сначала лимит — пропуск; потом лимит ушёл — тот же tick запускает."""
    watcher = FakeWatcher(active=True)
    app = make_app(watcher=watcher, next_run=past_iso(hours_ago=1))
    now = G.datetime.now()
    app._repeat_tick(app.saved_config, now)
    assert app.runner.starts == []
    watcher._active = False
    app._repeat_tick(app.saved_config, now)
    assert app.runner.starts == ["schedule"]
    nxt = G.parse_iso_time(app.saved_config.next_run)
    assert nxt is not None and nxt > now


def test_limit_gate_active_returns_false_without_watcher():
    app = make_app(watcher=None)
    assert app._limit_gate_active() is False
