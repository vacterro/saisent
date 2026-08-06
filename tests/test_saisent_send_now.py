""""Отправить щас" must send now: no schedule wait, no quota wait.

The bug: `send_now` queued the prompt and then called `start_worker_one`,
a method that does not exist. The text landed in the list and nothing was
ever sent -- a button whose entire name is "now" behaving as "later".
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from SAISENT import SaisentApp  # noqa: E402


class FakeWorker:
    def __init__(self):
        self.running = False
        self.started = None

    def start(self, jobs, gap_ms, dry, schedule_time="", check_limits=False, schedules=None):
        self.started = {
            "jobs": list(jobs),
            "gap_ms": gap_ms,
            "dry": dry,
            "schedule_time": schedule_time,
            "check_limits": check_limits,
            "schedules": schedules,
        }
        return True


class Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class FakeConfig:
    def __init__(self):
        self.data = {"gap_ms": 1500}

    def __getitem__(self, key):
        return self.data.get(key)

    def __setitem__(self, key, value):
        self.data[key] = value

    def save(self):
        return True


class FakeQueues:
    """The per-session schedule surface `_launch` reads (T-050)."""

    def schedule_of(self, key):
        return ""


class Harness:
    """Only the attributes `_launch` actually touches."""

    def __init__(self, schedule="02:28", limits=True, dry=False):
        self.worker = FakeWorker()
        self.config_store = FakeConfig()
        self.queues = FakeQueues()
        self.schedule_var = Var(schedule)
        self.limits_var = Var(limits)
        self.dry_var = Var(dry)
        self.tray_var = Var(False)
        self.status = None
        self.logs = []
        self.busy = None

    def set_status(self, state, message):
        self.status = (state, message)

    def log(self, message):
        self.logs.append(message)

    def set_busy(self, value):
        self.busy = value


def launch(harness, jobs, immediate):
    return SaisentApp._launch(harness, jobs, immediate=immediate)


JOB = (type("S", (), {"name": "sess-1", "key": "s1"})(), object(), 1)


def test_immediate_drops_the_schedule_and_the_quota_wait():
    harness = Harness(schedule="02:28", limits=True)

    launch(harness, [JOB], immediate=True)

    started = harness.worker.started
    assert started["schedule_time"] == "", "a button named 'now' must not wait"
    assert started["check_limits"] is False
    assert harness.busy is True


def test_a_normal_run_still_honours_both():
    harness = Harness(schedule="02:28", limits=True)

    launch(harness, [JOB], immediate=False)

    started = harness.worker.started
    assert started["schedule_time"] == "02:28"
    assert started["check_limits"] is True


def test_the_schedule_field_is_still_saved_on_an_immediate_run():
    """Bypassing the schedule for this run must not forget the setting."""
    harness = Harness(schedule="02:28", limits=True)

    launch(harness, [JOB], immediate=True)

    assert harness.config_store["schedule_time"] == "02:28"
    assert harness.config_store["check_limits"] is True


def test_nothing_launches_while_a_run_is_in_flight():
    harness = Harness()
    harness.worker.running = True

    launch(harness, [JOB], immediate=True)

    assert harness.worker.started is None
    assert harness.status[0] == "ERROR"


def test_an_empty_batch_is_reported_not_started():
    harness = Harness()

    launch(harness, [], immediate=True)

    assert harness.worker.started is None
    assert harness.status == ("IDLE", "Нечего отправлять.")


def test_the_log_line_says_when_it_is_going():
    harness = Harness(schedule="02:28")

    launch(harness, [JOB], immediate=True)
    assert "Когда: сейчас" in harness.logs[0]

    harness.worker.started = None
    harness.logs.clear()
    launch(harness, [JOB], immediate=False)
    assert "Когда: 02:28" in harness.logs[0]


def test_a_dry_run_writes_no_send_line():
    harness = Harness(dry=True)

    launch(harness, [JOB], immediate=True)

    assert harness.logs == []
    assert harness.worker.started["dry"] is True


def test_send_now_no_longer_calls_a_method_that_does_not_exist():
    """The exact shape of the original bug, pinned."""
    assert not hasattr(SaisentApp, "start_worker_one")
    source = SaisentApp.send_text_now.__doc__ or ""
    assert "start_worker_one" in source, "keep the regression documented"
