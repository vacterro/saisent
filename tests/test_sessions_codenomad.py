"""CodeNomad discovery, and the CDP profiles measured off the live pages."""

from __future__ import annotations

import sqlite3
import time

from SAISENT_sessions.deliver import (
    CDP_PORT_FILES,
    CDP_PROFILES,
    DEFAULT_WINDOW_TARGETS,
)
from SAISENT_sessions.discover import STATE_BUSY, STATE_IDLE, CodeNomadProvider


def make_db(path, sessions):
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE session (id TEXT PRIMARY KEY, project_id TEXT, slug TEXT,"
        " directory TEXT, title TEXT, agent TEXT, time_created INTEGER,"
        " time_updated INTEGER, time_archived INTEGER)"
    )
    connection.executemany(
        "INSERT INTO session (id, project_id, slug, directory, title, agent,"
        " time_created, time_updated, time_archived) VALUES (?,?,?,?,?,?,?,?,?)",
        sessions,
    )
    connection.execute(
        "CREATE TABLE part (id TEXT, message_id TEXT, session_id TEXT,"
        " time_created INTEGER, data TEXT)"
    )
    connection.commit()
    connection.close()


def provider(path, **kwargs):
    kwargs.setdefault("running", lambda _e: True)
    return CodeNomadProvider(db_path=path, **kwargs)


NOW_MS = 1_785_946_000_000
NOW = NOW_MS / 1000.0


def test_sessions_come_from_the_opencode_database(tmp_path):
    db = tmp_path / "opencode.db"
    make_db(
        db,
        [
            ("ses_a", "p1", "clever-star", "V:/proj/one", "Quick check-in",
             "build", NOW_MS - 60_000, NOW_MS - 5_000, None),
            ("ses_b", "p1", "silent-sailor", "V:/proj/one", "Schedule the job",
             "build", NOW_MS - 900_000, NOW_MS - 600_000, None),
        ],
    )

    found = provider(db).discover(now=NOW)

    assert [s.name for s in found] == ["Quick check-in", "Schedule the job"]
    assert [s.state for s in found] == [STATE_BUSY, STATE_IDLE]
    assert found[0].key == "codenomad:ses_a"
    assert found[0].agent == "codenomad"
    assert found[0].project_name == "one"


def test_only_the_open_project_is_listed(tmp_path):
    """CodeNomad renders one project's sessions; the rest cannot be clicked.

    Listing them offered targets whose dialog click finds nothing, so the
    send is refused — rows that exist only to fail.
    """
    db = tmp_path / "opencode.db"
    make_db(
        db,
        [
            ("ses_open", "p1", "s", "V:/proj/open", "In the open project",
             "build", NOW_MS - 60_000, NOW_MS - 5_000, None),
            ("ses_other", "p2", "s", "V:/proj/other", "Somewhere else",
             "build", NOW_MS - 900_000, NOW_MS - 600_000, None),
        ],
    )

    found = provider(db).discover(now=NOW)

    assert [s.name for s in found] == ["In the open project"]


def test_archived_sessions_are_gone(tmp_path):
    db = tmp_path / "opencode.db"
    make_db(
        db,
        [
            ("ses_a", "p", "s", "V:/p", "live", "build", NOW_MS, NOW_MS, None),
            ("ses_b", "p", "s", "V:/p", "closed", "build", NOW_MS, NOW_MS, NOW_MS),
        ],
    )
    assert [s.name for s in provider(db).discover(now=NOW)] == ["live"]


def test_stale_sessions_fall_out_of_the_window(tmp_path):
    db = tmp_path / "opencode.db"
    old = NOW_MS - 48 * 3600 * 1000
    make_db(db, [("ses_a", "p", "s", "V:/p", "ancient", "build", old, old, None)])

    assert provider(db, max_age_hours=24.0).discover(now=NOW) == []
    assert len(provider(db, max_age_hours=72.0).discover(now=NOW)) == 1


def test_nothing_is_listed_while_codenomad_is_closed(tmp_path):
    db = tmp_path / "opencode.db"
    make_db(db, [("ses_a", "p", "s", "V:/p", "live", "build", NOW_MS, NOW_MS, None)])

    closed = CodeNomadProvider(db_path=db, running=lambda _e: False)
    assert closed.discover(now=NOW) == []


def test_a_missing_database_is_empty_not_an_error(tmp_path):
    assert provider(tmp_path / "nope.db").discover(now=NOW) == []


def test_sessions_carry_no_tab_hint(tmp_path):
    """CodeNomad is addressed by name over the debugger; a tab index is a lie."""
    db = tmp_path / "opencode.db"
    make_db(db, [("ses_a", "p", "s", "V:/p", "one", "build", NOW_MS, NOW_MS, None)])

    assert provider(db).discover(now=NOW)[0].tab_hint is None


# ------------------------------------------------------------------ profiles
def test_every_cdp_profile_names_its_agent_and_a_field():
    for agent, profile in CDP_PROFILES.items():
        assert profile["agent"] == agent, "the override lookup keys on this"
        assert profile["selector"], "no field selector means typing into nothing"


def test_the_measured_selectors_are_the_ones_that_were_verified():
    """Pinned against the live DOM read on 2026-08-05.

    Antigravity: `button[class*="headerbtn"]` matched all 16 project buttons
    exactly. CodeNomad: `span.session-item-title` matched the session title.
    If an app redesigns, this test is the place the breakage gets noticed.
    """
    antigravity = CDP_PROFILES["antigravity"]["dialog_selector"]
    assert 'button[class*="headerbtn"]' in antigravity
    assert 'button[data-project-card="true"]' in antigravity
    assert "," in antigravity, "keep both spellings; a redesign renamed one"
    assert CDP_PROFILES["antigravity"]["selector"] == '[aria-label="Message input"]'
    assert "span.session-item-title" in CDP_PROFILES["codenomad"]["dialog_selector"]
    assert CDP_PROFILES["codenomad"]["selector"] == "textarea.prompt-input"


def test_dialog_source_matches_what_each_list_actually_shows():
    """Antigravity lists projects; CodeNomad lists session titles.

    Clicking with the wrong label finds nothing, which is how Antigravity
    ended up "just pressing Enter" in whatever chat was open.
    """
    assert CDP_PROFILES["antigravity"]["dialog_from"] == "project"
    assert CDP_PROFILES["codenomad"]["dialog_from"] == "name"


def test_codenomad_has_a_window_target_and_a_port_file():
    assert DEFAULT_WINDOW_TARGETS["codenomad"] == (
        "CodeNomad.exe",
        "Chrome_WidgetWin_1",
        "CodeNomad",
    )
    # Its Electron userData folder is still named after the shell it forked.
    assert CDP_PORT_FILES["codenomad"].endswith(r"Plasticity\DevToolsActivePort")


def test_freebuff_has_no_cdp_profile_because_its_port_is_not_a_debugger():
    """Freebuff's 127.0.0.1 port answers 401, not `/json/list`."""
    assert "freebuff" not in CDP_PROFILES
    assert "freebuff" not in CDP_PORT_FILES
