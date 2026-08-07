"""Session discovery: who is alive, what are they called, are they busy."""

from __future__ import annotations

import json
import os
import sqlite3
import time

import pytest

from SAISENT_sessions.discover import (
    STATE_BUSY,
    STATE_IDLE,
    AntigravityProvider,
    ClaudeCodeProvider,
    CodeNomadProvider,
    FreebuffProvider,
    SessionRegistry,
    project_slug,
)


# ---------------------------------------------------------------- helpers
def write_session(sessions_dir, pid, session_id, cwd, name, started_ms):
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (sessions_dir / f"{pid}.json").write_text(
        json.dumps(
            {
                "pid": pid,
                "sessionId": session_id,
                "cwd": cwd,
                "startedAt": started_ms,
                "kind": "interactive",
                "entrypoint": "claude-desktop",
                "name": name,
            }
        ),
        encoding="utf-8",
    )


def make_freebuff_db(path, threads):
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE threads (id TEXT PRIMARY KEY, project_id TEXT,"
        " project_path TEXT, title TEXT, status TEXT, turn_state TEXT,"
        " created_at INTEGER, updated_at INTEGER)"
    )
    connection.executemany(
        "INSERT INTO threads (id, project_id, project_path, title, status,"
        " turn_state, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
        threads,
    )
    connection.commit()
    connection.close()


# ------------------------------------------------------------ project_slug
def test_project_slug_matches_claude_code_layout():
    """Every non-alphanumeric character becomes exactly one dash."""
    assert (
        project_slug(r"V:\___VAC\__K\__CODE\_PY\_SAISENT")
        == "V-----VAC---K---CODE--PY--SAISENT"
    )


# --------------------------------------------------------------- ClaudeCode
def test_claude_code_lists_only_live_sessions(tmp_path):
    """The session file outlives the session; the PID check is the truth."""
    sessions = tmp_path / "sessions"
    write_session(sessions, 111, "aaa", r"V:\proj\one", "one-1", 1_000_000_000_000)
    write_session(sessions, 222, "bbb", r"V:\proj\two", "two-2", 1_000_000_001_000)

    provider = ClaudeCodeProvider(
        sessions_dir=sessions,
        projects_dir=tmp_path / "projects",
        alive=lambda pid: pid == 222,
    )
    found = provider.discover(now=2_000_000.0)

    assert [s.name for s in found] == ["two-2"]
    assert found[0].pid == 222
    assert found[0].key == "claude-code:bbb"
    assert found[0].project == r"V:\proj\two"


def test_claude_code_orders_by_start_and_claims_no_tab(tmp_path):
    """Order is start order; the tab hint stays empty on purpose.

    Measured: Ctrl+<digit> does not switch Claude Code sessions (a send aimed
    at tab 5 landed in the focused one) and Ctrl+N opens a new blank session.
    A number here would promise addressing that does not exist.
    """
    sessions = tmp_path / "sessions"
    write_session(sessions, 111, "aaa", r"V:\a", "first", 1_000_000_002_000)
    write_session(sessions, 222, "bbb", r"V:\b", "second", 1_000_000_001_000)

    provider = ClaudeCodeProvider(
        sessions_dir=sessions,
        projects_dir=tmp_path / "projects",
        alive=lambda pid: True,
    )
    found = provider.discover(now=2_000_000.0)

    assert [s.name for s in found] == ["second", "first"]
    assert [s.tab_hint for s in found] == [None, None]


def test_claude_code_sensor_reads_transcript_mtime(tmp_path):
    """A session that just wrote a turn is busy; a quiet one is idle."""
    sessions = tmp_path / "sessions"
    projects = tmp_path / "projects"
    cwd = r"V:\proj\one"
    write_session(sessions, 111, "aaa", cwd, "one-1", 1_000_000_000_000)

    transcript = projects / project_slug(cwd) / "aaa.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("{}", encoding="utf-8")
    now = time.time()

    provider = ClaudeCodeProvider(
        sessions_dir=sessions,
        projects_dir=projects,
        alive=lambda pid: True,
        busy_seconds=20.0,
    )

    assert provider.discover(now=now)[0].state == STATE_BUSY
    assert provider.discover(now=now + 3600)[0].state == STATE_IDLE


def test_claude_code_finds_transcript_when_slug_rule_misses(tmp_path):
    """A changed slug rule must not blind the sensor: fall back to a glob."""
    sessions = tmp_path / "sessions"
    projects = tmp_path / "projects"
    write_session(sessions, 111, "aaa", r"V:\proj\one", "one-1", 1_000_000_000_000)

    transcript = projects / "some-other-slug" / "aaa.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("{}", encoding="utf-8")

    provider = ClaudeCodeProvider(
        sessions_dir=sessions, projects_dir=projects, alive=lambda pid: True
    )
    assert provider.discover(now=time.time())[0].state == STATE_BUSY


def test_claude_code_survives_a_corrupt_session_file(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "bad.json").write_text("{not json", encoding="utf-8")
    write_session(sessions, 222, "bbb", r"V:\b", "good", 1_000_000_000_000)

    provider = ClaudeCodeProvider(
        sessions_dir=sessions,
        projects_dir=tmp_path / "projects",
        alive=lambda pid: True,
    )
    assert [s.name for s in provider.discover(now=2_000_000.0)] == ["good"]


def test_claude_code_missing_directory_is_empty_not_an_error(tmp_path):
    provider = ClaudeCodeProvider(
        sessions_dir=tmp_path / "nope",
        projects_dir=tmp_path / "projects",
        alive=lambda pid: True,
    )
    assert provider.discover(now=1.0) == []


# ----------------------------------------------------------------- Freebuff
def test_freebuff_reads_open_threads_with_its_own_turn_state(tmp_path):
    """`turn_state` is a real sensor: no timestamp inference needed."""
    db = tmp_path / "proj" / ".freebuff" / "desktop-v2.db"
    make_freebuff_db(
        db,
        [
            ("t1", "p", r"V:\proj", "running one", "open", "running", 10_000, 20_000),
            ("t2", "p", r"V:\proj", "idle one", "open", "idle", 11_000, 21_000),
            ("t3", "p", r"V:\proj", "closed one", "closed", "idle", 12_000, 22_000),
        ],
    )

    provider = FreebuffProvider(roots=[tmp_path], max_depth=2)
    found = provider.discover(now=time.time())

    assert [s.name for s in found] == ["running one", "idle one"]
    assert [s.state for s in found] == [STATE_BUSY, STATE_IDLE]
    assert found[0].key == "freebuff:t1"


def test_freebuff_scan_is_depth_limited(tmp_path):
    """A refresh must not walk an entire source tree."""
    deep = tmp_path / "a" / "b" / "c" / "d" / ".freebuff" / "desktop-v2.db"
    make_freebuff_db(deep, [("t1", "p", "x", "deep", "open", "idle", 1, 2)])

    assert FreebuffProvider(roots=[tmp_path], max_depth=2).discover(now=1.0) == []
    assert len(FreebuffProvider(roots=[tmp_path], max_depth=4).discover(now=1.0)) == 1


def test_freebuff_unreadable_database_is_skipped(tmp_path):
    db = tmp_path / "proj" / ".freebuff" / "desktop-v2.db"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"this is not a database")

    assert FreebuffProvider(roots=[tmp_path], max_depth=2).discover(now=1.0) == []


# -------------------------------------------------------------- Antigravity
def make_antigravity_db(path, workspace_uri):
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE trajectory_metadata_blob (id TEXT, data BLOB)")
    connection.execute(
        "INSERT INTO trajectory_metadata_blob VALUES (?, ?)",
        ("main", workspace_uri.encode("utf-8")),
    )
    connection.commit()
    connection.close()


def test_antigravity_names_a_conversation_after_its_workspace(tmp_path):
    db = tmp_path / "932a8d4e.db"
    make_antigravity_db(db, ")file:///v:/___VAC/__K/__CODE/_PY/_SAISENT")

    provider = AntigravityProvider(conversations_dir=tmp_path, running=lambda _e: True)
    found = provider.discover(now=time.time())

    assert len(found) == 1
    assert found[0].name == "_SAISENT"
    assert found[0].key == "antigravity:932a8d4e"


def test_antigravity_drops_conversations_older_than_the_window(tmp_path):
    """The store keeps every conversation forever; only recent ones are open."""
    db = tmp_path / "old.db"
    make_antigravity_db(db, "file:///v:/x")

    provider = AntigravityProvider(conversations_dir=tmp_path, max_age_hours=1.0)
    assert provider.discover(now=time.time() + 7200) == []


def test_antigravity_falls_back_to_the_conversation_id(tmp_path):
    db = tmp_path / "abcdef123456.db"
    make_antigravity_db(db, "no workspace here")

    provider = AntigravityProvider(conversations_dir=tmp_path, running=lambda _e: True)
    assert provider.discover(now=time.time())[0].name == "abcdef12"


def test_antigravity_collapses_conversations_of_one_workspace(tmp_path):
    """Its list switches PROJECTS, so two chats in one workspace are one row.

    The sidebar showed `_SAIPEN` three times; all three delivered to the same
    project button, so the extra rows were decoys, not choices.
    """
    for name in ("a.db", "b.db", "c.db"):
        make_antigravity_db(tmp_path / name, "file:///v:/proj/_SAIPEN")
    make_antigravity_db(tmp_path / "d.db", "file:///v:/proj/_OTHER")

    provider = AntigravityProvider(conversations_dir=tmp_path, running=lambda _e: True)
    found = provider.discover(now=time.time())

    assert sorted(s.name for s in found) == ["_OTHER", "_SAIPEN"]


def test_antigravity_keeps_the_freshest_conversation_of_a_workspace(tmp_path):
    older = tmp_path / "older.db"
    newer = tmp_path / "newer.db"
    make_antigravity_db(older, "file:///v:/proj/_SAIPEN")
    make_antigravity_db(newer, "file:///v:/proj/_SAIPEN")
    os.utime(older, (time.time() - 3600, time.time() - 3600))

    provider = AntigravityProvider(conversations_dir=tmp_path, running=lambda _e: True)
    found = provider.discover(now=time.time())

    assert len(found) == 1
    assert found[0].session_id == "newer"


def test_antigravity_lists_nothing_when_the_editor_is_closed(tmp_path):
    """Recency alone lied: this store keeps every conversation forever."""
    make_antigravity_db(tmp_path / "recent.db", "file:///v:/proj")

    closed = AntigravityProvider(conversations_dir=tmp_path, running=lambda _e: False)
    assert closed.discover(now=time.time()) == []

    open_editor = AntigravityProvider(
        conversations_dir=tmp_path, running=lambda _e: True
    )
    assert len(open_editor.discover(now=time.time())) == 1


def test_freebuff_lists_nothing_when_the_desktop_is_closed(tmp_path):
    """Threads stay `open` in the database long after the app quits."""
    db = tmp_path / "proj" / ".freebuff" / "desktop-v2.db"
    make_freebuff_db(db, [("t1", "p", r"V:\proj", "one", "open", "idle", 1, 2)])

    closed = FreebuffProvider(roots=[tmp_path], max_depth=2, running=lambda _e: False)
    assert closed.discover(now=1.0) == []

    running = FreebuffProvider(roots=[tmp_path], max_depth=2, running=lambda _e: True)
    assert len(running.discover(now=1.0)) == 1


# -------------------------------------------------------------- SessionRegistry
class _Stub:
    def __init__(self, agent, result=None, boom=False):
        self.agent = agent
        self.result = result or []
        self.boom = boom
        self.calls = 0

    def discover(self, now=None):
        self.calls += 1
        if self.boom:
            raise RuntimeError("provider exploded")
        return list(self.result)


def _session(agent, name):
    from SAISENT_sessions.discover import Session

    return Session(
        key=f"{agent}:{name}",
        agent=agent,
        name=name,
        project="",
        session_id=name,
        started=0.0,
        last_active=0.0,
    )


def test_registry_queries_only_enabled_providers():
    a = _Stub("claude-code", [_session("claude-code", "one")])
    b = _Stub("freebuff", [_session("freebuff", "two")])
    registry = SessionRegistry(providers=[a, b], enabled={"claude-code"})

    assert [s.name for s in registry.discover(now=1.0)] == ["one"]
    assert b.calls == 0

    registry.enable("freebuff")
    assert [s.name for s in registry.discover(now=1.0)] == ["one", "two"]


def test_registry_keeps_the_last_good_result_when_a_provider_throws():
    """A provider that breaks must not blank a sidebar somebody is reading."""
    stub = _Stub("freebuff", [_session("freebuff", "two")])
    registry = SessionRegistry(providers=[stub], enabled={"freebuff"})
    assert [s.name for s in registry.discover(now=1.0)] == ["two"]

    stub.boom = True
    assert [s.name for s in registry.discover(now=2.0)] == ["two"]
    assert "provider exploded" in registry.last_error


def test_registry_disabling_forgets_the_cache():
    stub = _Stub("freebuff", [_session("freebuff", "two")])
    registry = SessionRegistry(providers=[stub], enabled={"freebuff"})
    registry.discover(now=1.0)

    registry.enable("freebuff", False)
    stub.boom = True
    registry.enable("freebuff", True)
    assert registry.discover(now=2.0) == []


@pytest.mark.parametrize("agent", ["claude-code", "freebuff", "antigravity"])
def test_default_registry_carries_every_shipped_provider(agent):
    from SAISENT_sessions.discover import default_registry

    assert agent in default_registry().provider_names()


# ------------------------------------------- silent-failure logging (T-081)
def test_claude_code_logs_unreadable_session_file(tmp_path):
    """A corrupt session file is a finding, not something to shrug at."""
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "1.json").write_text("{not json", encoding="utf-8")
    lines: list[str] = []

    provider = ClaudeCodeProvider(
        sessions_dir=sessions,
        projects_dir=tmp_path / "projects",
        alive=lambda pid: True,
        log=lines.append,
    )
    assert provider.discover(now=1.0) == []
    assert any("unreadable session file" in line for line in lines)


def test_claude_code_logs_malformed_pid(tmp_path):
    """A session whose pid is not a number can never be a live session."""
    sessions = tmp_path / "sessions"
    write_session(sessions, "not-a-pid", "aaa", r"V:\proj\one", "one-1", 1)
    lines: list[str] = []

    provider = ClaudeCodeProvider(
        sessions_dir=sessions,
        projects_dir=tmp_path / "projects",
        alive=lambda pid: True,
        log=lines.append,
    )
    assert provider.discover(now=1.0) == []
    assert any("malformed pid" in line for line in lines)


def test_freebuff_logs_corrupt_database(tmp_path):
    """An unreadable Freebuff store must say so, not silently list nothing."""
    root = tmp_path / "proj"
    db = root / ".freebuff" / "desktop-v2.db"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"this is not a sqlite database at all")
    lines: list[str] = []

    provider = FreebuffProvider(
        roots=[root], max_depth=1, running=lambda _e: True, log=lines.append
    )
    assert provider.discover(now=1.0) == []
    assert any("discover: freebuff" in line for line in lines)


def test_codenomad_logs_corrupt_database(tmp_path):
    """CodeNomad's store failing must not read as 'no sessions today'."""
    db = tmp_path / "opencode.db"
    db.write_bytes(b"garbage")
    lines: list[str] = []

    provider = CodeNomadProvider(
        db_path=db, running=lambda _e: True, log=lines.append
    )
    assert provider.discover(now=1.0) == []
    assert any("discover: codenomad" in line for line in lines)


def test_registry_logs_a_provider_failure():
    """The registry speaks too: a broken provider is a log line, not a blank."""
    stub = _Stub("freebuff", [_session("freebuff", "two")])
    lines: list[str] = []
    registry = SessionRegistry(
        providers=[stub], enabled={"freebuff"}, log=lines.append
    )
    registry.discover(now=1.0)

    stub.boom = True
    assert [s.name for s in registry.discover(now=2.0)] == ["two"]
    assert any("provider failed" in line for line in lines)


def test_no_log_sink_keeps_discovery_silent(tmp_path):
    """A caller that passes nothing keeps the old no-op behaviour."""
    root = tmp_path / "proj"
    db = root / ".freebuff" / "desktop-v2.db"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"not sqlite")

    provider = FreebuffProvider(roots=[root], max_depth=1, running=lambda _e: True)
    assert provider.discover(now=1.0) == []
