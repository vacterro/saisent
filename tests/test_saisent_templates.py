"""Prompt templates with variable expansion (T-051).

A saved template may carry {session} / {project} / {date} / {time}
placeholders. Inserting it expands them against the selected session;
unknown placeholders stay literal so a typo stays visible instead of
vanishing into a send.
"""

import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from SAISENT import expand_template  # noqa: E402
from SAISENT_sessions.discover import Session  # noqa: E402


def session():
    return Session(
        key="s1", agent="antigravity", name="sess-1",
        project="V:\\proj\\myproj", session_id="id", started=0.0, last_active=0.0,
    )


def test_project_expands_to_project_slug():
    out = expand_template("Работай над {project}", session())
    assert out == "Работай над myproj"


def test_session_expands_to_name():
    out = expand_template("Привет, {session}", session())
    assert out == "Привет, sess-1"


def test_date_and_time_expand_to_now():
    out = expand_template("{date} {time}", session())
    now = datetime.now()
    assert out == f"{now.strftime('%Y-%m-%d')} {now.strftime('%H:%M')}"


def test_unknown_placeholder_stays_literal():
    out = expand_template("{project} {typo}", session())
    assert "{typo}" in out, "a typo must stay visible, never silently eaten"


def test_no_session_leaves_session_and_project_literal():
    out = expand_template("{session}/{project}", None)
    assert out == "{session}/{project}"


def test_multiple_occurrences_all_expand():
    out = expand_template("{project} и {project}", session())
    assert out == "myproj и myproj"
