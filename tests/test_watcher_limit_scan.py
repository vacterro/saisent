"""CDP limit scan: how each agent's "am I rate-limited" answer is built.

`limit_scan.py` has two inputs -- the live page over the debugger socket and
the agent's own store on disk -- and turns either into an `AgentLimit`. The
socket layer is injected, so the whole sweep is testable without an agent
running. These tests pin: the fallback order (live first, disk second), the
many ways an agent can be "unreachable" (each producing a distinct reason),
and that a stale store row is never read as a current limit.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta

from SAISENT_watcher.limit_scan import (
    AgentLimit,
    limited,
    read_agent_text,
    read_agent_text_on_disk,
    scan_all,
    scan_agent,
)
from SAISENT_watcher.probes import FileProbe, SqliteProbe


class FakeWS:
    def __init__(self, result=None, explode=False):
        self.result = result or {"result": {"value": ""}}
        self.explode = explode
        self.closed = False
        self.calls = []

    def call(self, method, params=None):
        self.calls.append((method, params))
        if self.explode:
            raise RuntimeError("ws boom")
        return self.result

    def close(self):
        self.closed = True


class FakeTarget:
    def __init__(self, ws_url="ws://agent:9222/devtools"):
        self.ws_url = ws_url


class StubAdapter:
    def __init__(self, name="agent", transport="cdp", port=9222, title="",
                 probes=(), enabled=True, live=None, live_boom=False):
        self.name = name
        self.transport = transport
        self.cdp_port = port
        self.cdp_title = title
        self.probes = list(probes)
        self.enabled = enabled
        self._live = live
        self._live_boom = live_boom

    def live_cdp_port(self):
        if self._live_boom:
            raise RuntimeError("port probe boom")
        if self._live is None:
            return self.cdp_port
        return self._live


def make_db(path, ts_ms, body):
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE messages (id INTEGER, ts INTEGER, body TEXT)")
    connection.execute(
        "INSERT INTO messages VALUES (1, ?, ?)", (ts_ms, body)
    )
    connection.commit()
    connection.close()


NOW = datetime.now()
NOW_TS = time.time()


# ------------------------------------------------------------- AgentLimit
def test_unreachable_is_not_a_limit():
    result = AgentLimit("a", error="no debug port")
    assert not result.reachable
    assert not result.state.reached


def test_a_clean_reading_is_reachable_and_free():
    result = AgentLimit("a")
    assert result.reachable
    assert not result.state.reached


# --------------------------------------------------------- read_agent_text
def test_reads_the_visible_text_off_the_page():
    ws = FakeWS({"result": {"value": "Daily free limit reached"}})
    text = read_agent_text(FakeTarget(), connect=lambda url: ws)
    assert "limit reached" in text
    assert ws.closed  # the socket must not leak


def test_returns_empty_for_a_missing_target():
    assert read_agent_text(None) == ""
    assert read_agent_text(FakeTarget(ws_url="")) == ""


def test_closes_the_socket_even_when_the_call_throws():
    ws = FakeWS(explode=True)
    try:
        read_agent_text(FakeTarget(), connect=lambda url: ws)
    except RuntimeError:
        pass
    assert ws.closed


# --------------------------------------------------- read_agent_text_on_disk
def test_a_fresh_store_row_is_returned(tmp_path):
    db = tmp_path / "store.db"
    make_db(db, int((NOW_TS + 60) * 1000), "Daily free limit reached for this project")
    adapter = StubAdapter(probes=[SqliteProbe(str(db))])
    text = read_agent_text_on_disk(adapter, now=NOW_TS)
    assert "limit reached" in text


def test_a_stale_store_row_is_dropped(tmp_path):
    db = tmp_path / "store.db"
    make_db(db, int((NOW_TS - 8 * 3600) * 1000), "Daily free limit reached")
    adapter = StubAdapter(probes=[SqliteProbe(str(db))])
    assert read_agent_text_on_disk(adapter, now=NOW_TS) == ""


def test_a_missing_store_is_not_an_answer():
    adapter = StubAdapter(probes=[SqliteProbe("V:\\_TEMP_\\opencode\\nope.db")])
    assert read_agent_text_on_disk(adapter, now=NOW_TS) == ""


def test_a_recent_file_tail_is_returned(tmp_path):
    f = tmp_path / "log.jsonl"
    f.write_text("noise\n" * 100 + "usage limit reached\n", encoding="utf-8")
    adapter = StubAdapter(probes=[FileProbe(str(tmp_path / "log.jsonl"))])
    text = read_agent_text_on_disk(adapter, now=NOW_TS)
    assert "limit reached" in text


def test_a_stale_file_is_skipped(tmp_path):
    f = tmp_path / "old.jsonl"
    f.write_text("usage limit reached\n", encoding="utf-8")
    old = time.time() - 8 * 3600
    import os
    os.utime(f, (old, old))
    adapter = StubAdapter(probes=[FileProbe(str(f))])
    assert read_agent_text_on_disk(adapter, now=NOW_TS) == ""


# ----------------------------------------------------------------- scan_agent
def test_non_cdp_adapter_falls_back_to_the_disk_store():
    adapter = StubAdapter(transport="post", probes=[], enabled=True)
    result = scan_agent(adapter, now=NOW)
    assert not result.reachable
    assert "debugger" in result.error


def test_no_debug_port_is_a_distinct_reason():
    adapter = StubAdapter(transport="cdp", port=0)
    result = scan_agent(adapter, now=NOW)
    assert not result.reachable
    assert "no debug port" in result.error


def test_a_live_page_answer_carries_the_port():
    ws = FakeWS({"result": {"value": "Daily free limit reached"}})
    adapter = StubAdapter(transport="cdp", port=9222)
    result = scan_agent(
        adapter,
        connect=lambda url: ws,
        target_fn=lambda port, title: FakeTarget(),
        now=NOW,
    )
    assert result.reachable
    assert result.state.reached
    assert result.port == 9222


def test_no_readable_text_falls_back_to_disk():
    ws = FakeWS({"result": {"value": ""}})
    adapter = StubAdapter(transport="cdp", port=9222)
    result = scan_agent(
        adapter,
        connect=lambda url: ws,
        target_fn=lambda port, title: FakeTarget(),
        now=NOW,
    )
    assert not result.reachable
    assert "no readable text" in result.error


def test_a_not_running_page_is_an_answer_not_a_crash():
    adapter = StubAdapter(transport="cdp", port=9222)
    result = scan_agent(
        adapter,
        target_fn=lambda port, title: None,
        now=NOW,
    )
    assert not result.reachable
    assert "not running" in result.error


def test_a_port_probe_failure_degrades_to_the_cached_port():
    adapter = StubAdapter(transport="cdp", port=9222, live_boom=True)
    result = scan_agent(
        adapter,
        target_fn=lambda port, title: None,
        now=NOW,
    )
    assert not result.reachable  # live_cdp_port fell back to cdp_port, page absent


def test_disk_is_forbidden_when_allow_disk_is_false():
    adapter = StubAdapter(transport="cdp", port=0)
    result = scan_agent(adapter, now=NOW, allow_disk=False)
    assert not result.reachable
    assert result.error == "no debug port"


# --------------------------------------------------------------- sweep level
def test_scan_all_skips_disabled_adapters_and_keeps_order():
    a = StubAdapter(name="a", transport="post", enabled=True)
    b = StubAdapter(name="b", transport="post", enabled=False)
    c = StubAdapter(name="c", transport="post", enabled=True)
    out = scan_all([a, b, c], now=NOW)
    assert [r.name for r in out] == ["a", "c"]


def test_limited_filters_to_reached_only():
    yes = AgentLimit("a", port=1)
    yes.state.reached = True
    free = AgentLimit("b")
    dead = AgentLimit("c", error="no debug port")
    assert [r.name for r in limited([yes, free, dead])] == ["a"]
