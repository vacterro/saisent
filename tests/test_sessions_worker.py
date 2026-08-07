"""SendWorker state machine: stops, gates, pacing, crash safety (T-079).

`test_saisent_worker_honesty.py` pins what a delivery may claim. This file
pins how the batch MACHINE behaves: a stop anywhere aborts cleanly, the quota
gate holds and releases, pacing waits between items, the busy-wait is bounded,
and an unexpected deliverer failure still reports a result instead of leaving
the console frozen on a stuck daemon thread.
"""

from __future__ import annotations

import threading
import time

from SAISENT import SendWorker  # noqa: E402
from SAISENT_sessions.deliver import DeliveryResult  # noqa: E402
from SAISENT_sessions.discover import STATE_BUSY, STATE_IDLE, Session  # noqa: E402
from SAISENT_sessions.queues import PromptItem, STATE_PENDING  # noqa: E402


class FakeDeliverer:
    def __init__(self, results=(), raise_on=None):
        self.results = list(results)
        self.raise_on = raise_on
        self.calls = []

    def deliver(self, session, text, tab_index, dry=False):
        self.calls.append((text, tab_index, dry))
        if self.raise_on is not None and len(self.calls) == self.raise_on:
            raise RuntimeError("delivery exploded")
        return self.results.pop(0)


class BlockingDeliverer:
    def __init__(self):
        self.release = threading.Event()

    def deliver(self, session, text, tab_index, dry=False):
        self.release.wait(5)
        return DeliveryResult(True, "sent", confirmed=True)


class FakeRegistry:
    def __init__(self, sessions):
        self.sessions = list(sessions)

    def discover(self, now=None):
        return list(self.sessions)


def session(key="s1", state=STATE_IDLE):
    return Session(
        key=key, agent="antigravity", name=f"sess-{key}",
        project="V:\\proj", session_id=key, started=0.0, last_active=0.0,
        state=state,
    )


def item(text="gg"):
    return PromptItem(text=text)


def ok(reason="sent"):
    return DeliveryResult(True, reason, confirmed=True)


class FlipReading:
    """Blocks on the first scan, frees on the second -- a reset arriving."""

    def __init__(self):
        self.times = 0

    def blocking(self, wall):
        self.times += 1
        return self.times < 2

    def label(self, wall):
        return "тест"


class HardBlockedReading:
    def blocking(self, wall):
        return True

    def label(self, wall):
        return "тест"


class FreeReading:
    def blocking(self, wall):
        return False

    def label(self, wall):
        return "тест"


class FakeMonitor:
    def __init__(self, reading, raise_on_scan=False):
        self.reading_value = reading
        self.raise_on_scan = raise_on_scan
        self.scanned = []

    def scan(self, agents, now=None):
        self.scanned.append(list(agents))
        if self.raise_on_scan:
            raise RuntimeError("scan failed")

    def reading(self, agent):
        return self.reading_value


def build(jobs, results=(), registry=None, deliverer=None):
    """A worker wired to a scripted deliverer; returns (worker, reports, jobs)."""
    reports = []
    d = deliverer or FakeDeliverer(results)
    worker = SendWorker(d, reports.append, registry)
    return worker, reports, list(jobs)


def fast(worker):
    """Make every internal 1-second sleep a no-op so tests do not crawl."""
    worker._stop.wait = lambda _t: None
    return worker


# ---------------------------------------------------------------- the gate
def test_start_refuses_while_already_running():
    deliverer = BlockingDeliverer()
    worker, reports, jobs = build([(session(), item(), None)], deliverer=deliverer)
    assert worker.start(jobs, gap_ms=0, dry=False) is True
    assert worker.running
    assert worker.start(jobs, gap_ms=0, dry=False) is False

    deliverer.release.set()
    worker._thread.join(timeout=2)
    assert not worker.running


# ----------------------------------------------------------- the schedule
def test_a_stop_during_the_schedule_wait_aborts_cleanly():
    worker, reports, jobs = build([(session(), item(), None)])
    worker.stop()
    worker._run(jobs, gap_ms=0, dry=False, schedule_time="23:00", check_limits=False)

    done = [r for r in reports if r[0] == "done"]
    assert done and done[-1][1][1] == "остановлено"


# ------------------------------------------------------------- the quota
def test_the_quota_gate_holds_until_the_reset_lands():
    worker, reports, jobs = build([(session(), item(), None)], [ok()])
    fast(worker)
    worker.limit_monitor = FakeMonitor(FlipReading())
    worker._run(jobs, gap_ms=0, dry=False, schedule_time="", check_limits=True)

    done = [r for r in reports if r[0] == "done"]
    assert done[-1][1][0] == 1  # the prompt eventually went
    statuses = [r[1][1] for r in reports if r[0] == "status"]
    assert any("Жду сброса лимита" in s for s in statuses)


def test_a_free_quota_does_not_pause_the_batch():
    worker, reports, jobs = build([(session(), item(), None)], [ok()])
    fast(worker)
    worker.limit_monitor = FakeMonitor(FreeReading())
    worker._run(jobs, gap_ms=0, dry=False, schedule_time="", check_limits=True)

    statuses = [r[1][1] for r in reports if r[0] == "status"]
    assert not any("Жду сброса" in s for s in statuses)
    done = [r for r in reports if r[0] == "done"]
    assert done[-1][1][0] == 1


def test_a_quota_scan_failure_is_logged_and_the_batch_continues():
    worker, reports, jobs = build([(session(), item(), None)], [ok()])
    fast(worker)
    worker.limit_monitor = FakeMonitor(FreeReading(), raise_on_scan=True)
    worker._run(jobs, gap_ms=0, dry=False, schedule_time="", check_limits=True)

    logs = [r[1][0] for r in reports if r[0] == "log"]
    assert any("Проверка лимита" in line for line in logs)
    done = [r for r in reports if r[0] == "done"]
    assert done[-1][1][0] == 1


def test_a_stop_while_blocked_on_quota_emits_stopped():
    worker, reports, jobs = build([(session(), item(), None)])
    fast(worker)
    worker.limit_monitor = FakeMonitor(HardBlockedReading())
    worker.stop()
    worker._run(jobs, gap_ms=0, dry=False, schedule_time="", check_limits=True)

    done = [r for r in reports if r[0] == "done"]
    assert done and done[-1][1][1] == "остановлено"
    assert jobs[0][1].state == STATE_PENDING  # nothing was sent


# -------------------------------------------------------------- the pacing
def test_pacing_waits_between_items():
    worker, reports, jobs = build(
        [(session("a"), item("one"), None), (session("b"), item("two"), None)],
        [ok(), ok()],
    )
    started = time.perf_counter()
    worker._run(jobs, gap_ms=120, dry=False, schedule_time="", check_limits=False)
    elapsed = time.perf_counter() - started

    assert len(worker.deliverer.calls) == 2  # both delivered
    assert elapsed >= 0.12


# ------------------------------------------------------------ the busy wait
class AlwaysBusyRegistry(FakeRegistry):
    def __init__(self):
        self.sessions = [session("a", state=STATE_BUSY), session("b")]

    def discover(self, now=None):
        return list(self.sessions)


def test_the_post_send_busy_wait_is_bounded():
    worker, reports, jobs = build(
        [(session("a"), item("one"), None), (session("b"), item("two"), None)],
        [ok(), ok()],
        registry=AlwaysBusyRegistry(),
    )
    fast(worker)
    worker.busy_wait_seconds = 0.2
    started = time.perf_counter()
    worker._run(jobs, gap_ms=0, dry=False, schedule_time="", check_limits=False)
    elapsed = time.perf_counter() - started

    assert len(worker.deliverer.calls) == 2  # the second prompt still went
    assert 0.15 <= elapsed < 5.0  # bounded, never parked forever


# ----------------------------------------------------------- crash safety
def test_a_deliverer_crash_is_reported_and_does_not_hang():
    deliverer = FakeDeliverer([ok()], raise_on=2)
    worker, reports, jobs = build(
        [(session("a"), item("one"), None), (session("b"), item("two"), None)],
        deliverer=deliverer,
    )
    worker._run(jobs, gap_ms=0, dry=False, schedule_time="", check_limits=False)

    done = [r for r in reports if r[0] == "done"]
    assert done and "сбой" in done[-1][1][1]


def test_a_stop_mid_batch_skips_the_remaining_prompts():
    reports = []
    deliverer = FakeDeliverer([ok()])
    worker = SendWorker(deliverer, reports.append)
    original = deliverer.deliver

    def stopping_deliver(session, text, tab_index, dry=False):
        worker.stop()
        return original(session, text, tab_index, dry)

    deliverer.deliver = stopping_deliver
    jobs = [(session("a"), item("one"), None), (session("b"), item("two"), None)]

    worker._run(jobs, gap_ms=0, dry=False, schedule_time="", check_limits=False)

    assert len(deliverer.calls) == 1
    done = [r for r in reports if r[0] == "done"]
    assert done and done[-1][1][1] == "остановлено"


# ------------------------------------------------------------- resolve_session
def test_resolve_session_returns_none_when_the_session_is_gone():
    worker, reports, _ = build([], registry=FakeRegistry([]))
    assert worker.resolve_session(session("gone")) is None


def test_resolve_session_returns_the_snapshot_without_a_registry():
    worker, reports, _ = build([])
    assert worker.resolve_session(session("s1")).key == "s1"
