"""Per-session schedule override (T-050).

A queue can name its own HH:MM instead of inheriting the global
schedule_time, so two sessions fire at different times in one night. The
store persists the override; the worker splits a batch into segments by
effective time (own > global) and waits for each segment's time.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from SAISENT_sessions.discover import Session  # noqa: E402
from SAISENT_sessions.queues import PromptItem, QueueStore  # noqa: E402


def session(key="s1"):
    return Session(
        key=key, agent="antigravity", name=f"sess-{key}",
        project="V:\\proj", session_id="id", started=0.0, last_active=0.0,
    )


# ---------------------------------------------------------------- store
def test_schedule_round_trip(tmp_path):
    path = tmp_path / "queues.json"
    store = QueueStore(path)
    store.set_schedule("s1", "23:00")
    store.add("s1", "gg")
    assert store.save()
    assert store.schedule_of("s1") == "23:00"

    reloaded = QueueStore(path)
    assert reloaded.load()
    assert reloaded.schedule_of("s1") == "23:00"
    assert reloaded.pending("s1"), "queue content survives with the schedule"


def test_schedule_clear_and_unknown(tmp_path):
    store = QueueStore(tmp_path / "q.json")
    assert store.schedule_of("nobody") == ""
    store.set_schedule("s1", "23:00")
    store.set_schedule("s1", "   ")
    assert store.schedule_of("s1") == "", "blank clears the override"


def test_schedule_survives_missing_field(tmp_path):
    path = tmp_path / "q.json"
    path.write_text('{"version": 1, "labels": {}, "queues": {}}', encoding="utf-8")
    store = QueueStore(path)
    assert store.load()
    assert store.schedule_of("s1") == ""


# --------------------------------------------------------------- worker
class _SegmentsWorker:
    """Mirror of SendWorker's segment-splitting, exercised without threads."""

    def __init__(self):
        self.segments = []

    def _run(self, jobs, schedule_time, schedules=None):
        segments = {}
        for session, item, tab_index in jobs:
            own = (schedules or {}).get(session.key, "")
            key = own or schedule_time
            segments.setdefault(key, []).append(session.key)
        self.segments = [
            (t, sorted(keys)) for t, keys in sorted(
                segments.items(), key=lambda kv: (kv[0] == "", kv[0])
            )
        ]


def test_worker_splits_by_effective_time():
    w = _SegmentsWorker()
    jobs = [
        (session("a"), PromptItem(text="1"), None),
        (session("b"), PromptItem(text="2"), None),
        (session("c"), PromptItem(text="3"), None),
    ]
    # a has its own 23:00; b inherits the global 22:00; c has own 23:30.
    w._run(jobs, "22:00", schedules={"a": "23:00", "c": "23:30"})
    assert w.segments == [
        ("22:00", ["b"]),
        ("23:00", ["a"]),
        ("23:30", ["c"]),
    ]


def test_worker_schedules_param_defaults_to_inherit():
    w = _SegmentsWorker()
    jobs = [(session("a"), PromptItem(text="1"), None)]
    w._run(jobs, "22:00", None)
    assert w.segments == [("22:00", ["a"])]
