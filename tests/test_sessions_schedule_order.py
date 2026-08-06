"""Segment ordering: "now" first, then by the clock, and never on a typo."""

from __future__ import annotations

from datetime import datetime, timedelta

from SAISENT import SendWorker
from SAISENT_sessions.deliver import DeliveryResult
from SAISENT_sessions.discover import Session
from SAISENT_sessions.queues import STATE_FAILED, PromptItem

NOW = datetime(2026, 8, 6, 21, 0, 0)


class FakeDeliverer:
    def __init__(self, count=9):
        self.calls = []
        self.count = count

    def deliver(self, session, text, tab_index, dry=False):
        self.calls.append(text)
        return DeliveryResult(True, "sent", confirmed=True)


def session(key):
    return Session(
        key=key, agent="claude-code", name=key, project="V:/p",
        session_id=key, started=0.0, last_active=0.0,
    )


def build(reports):
    worker = SendWorker(FakeDeliverer(), reports.append)
    worker._wait_for_time = lambda t: waited.append(t) or True
    return worker


waited: list = []


# ------------------------------------------------------------ next_occurrence
def test_a_past_time_rolls_to_tomorrow():
    assert SendWorker.next_occurrence("03:00", NOW) == datetime(2026, 8, 7, 3, 0)


def test_a_future_time_is_today():
    assert SendWorker.next_occurrence("23:30", NOW) == datetime(2026, 8, 6, 23, 30)


def test_an_unreadable_time_is_none_not_now():
    """The old code swallowed the error and sent immediately."""
    for bad in ("", "nope", "25:00", "12:99", "12", None):
        assert SendWorker.next_occurrence(bad, NOW) is None, bad


# ---------------------------------------------------------------- ordering
def run(schedules, global_time=""):
    waited.clear()
    reports = []
    worker = build(reports)
    jobs = [
        (session(key), PromptItem(text=key), None) for key in sorted(schedules)
    ]
    worker._run(jobs, gap_ms=0, dry=False, schedule_time=global_time,
                check_limits=False, schedules=schedules, now=NOW)
    return worker.deliverer.calls, reports


def test_immediate_jobs_go_before_a_scheduled_one():
    """One session carrying an override used to park every 'send now' job."""
    order, _reports = run({"now-job": "", "late-job": "03:00"})
    assert order[0] == "now-job"


def test_scheduled_segments_run_in_clock_order_not_string_order():
    """Tonight 23:00 must not queue behind tomorrow 03:00."""
    order, _reports = run({"tonight": "23:30", "tomorrow": "03:00"})
    assert order == ["tonight", "tomorrow"]
    assert waited == ["23:30", "03:00"]


def test_a_typo_in_an_override_fails_that_job_instead_of_sending_it():
    order, _reports = run({"good": "", "typo": "3 o'clock"})

    assert "typo" not in order, "an unreadable time must never send immediately"
    assert order == ["good"]


def test_the_typo_job_is_marked_failed_with_the_reason():
    waited.clear()
    reports = []
    worker = build(reports)
    item = PromptItem(text="typo")
    worker._run([(session("s"), item, None)], gap_ms=0, dry=False,
                schedule_time="", check_limits=False, schedules={"s": "nope"},
                now=NOW)

    assert item.state == STATE_FAILED
    assert "нечитаемое время" in item.reason
