"""Queue next-fire display (T-062).

The queue row now says when it fires: the session's own HH:MM wins over the
global schedule, empty means "now", and the label is computed by the same
`next_occurrence` the worker sorts by -- so the display cannot disagree with
the send.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from SAISENT import next_fire_label  # noqa: E402

NOW = datetime(2026, 8, 6, 21, 0, 0)


def test_empty_everything_means_now():
    assert next_fire_label("", "", NOW) == "сейчас"


def test_own_time_wins_over_global():
    label = next_fire_label("03:00", "23:30", NOW)
    assert label.startswith("03:00")
    assert "завтра" in label  # 03:00 tonight is already past at 21:00


def test_future_global_time_is_today():
    label = next_fire_label("", "23:30", NOW)
    assert label.startswith("23:30")
    assert "сегодня" in label


def test_an_unreadable_time_says_so_not_now():
    label = next_fire_label("3 o'clock", "", NOW)
    assert "нечитаемое" in label
    assert "сейчас" not in label


def test_label_matches_next_occurrence():
    from SAISENT import SendWorker

    target = SendWorker.next_occurrence("23:30", NOW)
    label = next_fire_label("", "23:30", NOW)
    assert label.startswith("23:30")
    assert ("сегодня" if target.date() == NOW.date() else "завтра") in label
