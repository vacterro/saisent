"""SendWorker honesty: a send is only "ушло" when the session confirmed it.

The bug that prompted this file: the worker marked an item STATE_SENT and
counted it in "Отправлено N" on the strength of `result.ok` alone. But
`deliver()` returns ok=True even when nothing was confirmed ("sent, but the
session showed no activity yet") — a quota-blocked agent, a busy turn. The
UI then said «ушло, Отправлено 1: готово» while nothing had arrived. These
tests pin the honest behaviour: unconfirmed stays queued, dry runs touch
nothing, only a confirmed send becomes "ушло".
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from SAISENT import SendWorker  # noqa: E402
from SAISENT_sessions.deliver import DeliveryResult  # noqa: E402
from SAISENT_sessions.discover import Session  # noqa: E402
from SAISENT_sessions.queues import (  # noqa: E402
    STATE_FAILED,
    STATE_PENDING,
    STATE_SENT,
    PromptItem,
)


class FakeDeliverer:
    """Returns scripted DeliveryResults; records what was asked."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def deliver(self, session, text, tab_index, dry=False):
        self.calls.append((text, tab_index, dry))
        return self.results.pop(0)


def session(key="s1"):
    return Session(
        key=key, agent="antigravity", name="sess-1",
        project="V:\\proj", session_id="id", started=0.0, last_active=0.0,
    )


def run(results, dry=False):
    """Run the worker synchronously, one job per scripted result.

    One job per result, not one job total: a "mixed run" needs as many jobs as
    it has outcomes, and a helper that queues one job while scripting three
    answers silently tests something else.
    """
    reports = []
    deliverer = FakeDeliverer(results)
    worker = SendWorker(deliverer, reports.append)
    items = [PromptItem(text="gg") for _ in results]
    jobs = [(session(f"s{n}"), item, 1) for n, item in enumerate(items)]
    worker._run(jobs, gap_ms=0, dry=dry, schedule_time="", check_limits=False)
    return reports, items[0], deliverer


def item_states(reports):
    return [args for kind, args in reports if kind == "item_state"]


def done_args(reports):
    return [args for kind, args in reports if kind == "done"][0]


def test_unconfirmed_send_stays_pending_not_ushlo():
    """The exact case from the log: `OK (unconfirmed): sent, but the
    session showed no activity yet` must NOT become «ушло»."""
    reports, item, _ = run([
        DeliveryResult(True, "sent, but the session showed no activity yet"),
    ])
    final = item_states(reports)[-1]
    assert final[2] == STATE_PENDING, "unconfirmed must stay in the queue"
    assert final[4] is False, "confirmed flag must reach the store"
    assert item.state == STATE_PENDING
    sent, reason = done_args(reports)
    assert sent == 0, "an unconfirmed send is not an отправленный prompt"
    assert "не подтверждено" in reason


def test_confirmed_send_is_ushlo():
    reports, item, _ = run([
        DeliveryResult(True, "sent", confirmed=True),
    ])
    final = item_states(reports)[-1]
    assert final[2] == STATE_SENT
    assert final[4] is True
    assert item.state == STATE_SENT
    sent, reason = done_args(reports)
    assert sent == 1
    assert "не подтверждено" not in reason


def test_failed_send_is_marked_failed_and_counted():
    reports, item, _ = run([
        DeliveryResult(False, "window not found"),
    ])
    final = item_states(reports)[-1]
    assert final[2] == STATE_FAILED
    assert item.state == STATE_FAILED
    sent, reason = done_args(reports)
    assert sent == 0
    assert "1 с ошибкой" in reason


def test_a_failure_no_longer_kills_the_rest_of_the_batch():
    """Overnight, one bad target used to mean nothing behind it ever went.

    The failure is reported and counted; the prompts after it still go out.
    """
    reports, _item, deliverer = run([
        DeliveryResult(False, "window not found"),
        DeliveryResult(True, "sent", confirmed=True),
        DeliveryResult(True, "sent", confirmed=True),
    ])

    assert len(deliverer.calls) == 3, "every job must be attempted"
    sent, reason = done_args(reports)
    assert sent == 2
    assert "1 с ошибкой" in reason


def test_dry_run_touches_nothing():
    """A пробный прогон must not mark anything sent — nothing went out."""
    reports, item, deliverer = run([
        DeliveryResult(True, "dry run: nothing sent"),
    ], dry=True)
    assert item.state == STATE_PENDING, "dry run leaves the queue alone"
    assert deliverer.calls and deliverer.calls[0][2] is True
    sent, reason = done_args(reports)
    assert sent == 0


class FakeRegistry:
    """A registry that reports whichever sessions are 'alive' right now."""

    def __init__(self, alive):
        self.alive = list(alive)

    def discover(self, now=None):
        return list(self.alive)


def test_a_session_that_died_while_the_batch_waited_is_skipped():
    """A batch queued at 22:00 for 03:00 holds hours-old Session objects.

    Delivering to one whose session is gone resolves the agent's window anyway
    and pastes into whatever chat is open there.
    """
    reports = []
    deliverer = FakeDeliverer([DeliveryResult(True, "sent", confirmed=True)])
    worker = SendWorker(deliverer, reports.append, FakeRegistry([]))
    item = PromptItem(text="gg")

    worker._run([(session("gone"), item, 1)], gap_ms=0, dry=False,
                schedule_time="", check_limits=False)

    assert deliverer.calls == [], "nothing may be typed for a dead session"
    assert item.state == STATE_FAILED
    assert "сессия закрылась" in item.reason
    sent, reason = done_args(reports)
    assert sent == 0
    assert "пропущено" in reason


def test_a_live_session_is_re_resolved_not_taken_from_the_snapshot():
    """The fresh record wins: its tab hint and name may have changed."""
    stale = session("s1")
    fresh = session("s1")
    fresh.name = "renamed"
    fresh.tab_hint = 7
    reports = []
    deliverer = FakeDeliverer([DeliveryResult(True, "sent", confirmed=True)])
    worker = SendWorker(deliverer, reports.append, FakeRegistry([fresh]))

    worker._run([(stale, PromptItem(text="gg"), 1)], gap_ms=0, dry=False,
                schedule_time="", check_limits=False)

    assert deliverer.calls == [("gg", 7, False)]


def test_without_a_registry_the_snapshot_still_stands():
    reports = []
    deliverer = FakeDeliverer([DeliveryResult(True, "sent", confirmed=True)])
    worker = SendWorker(deliverer, reports.append, None)

    worker._run([(session(), PromptItem(text="gg"), 1)], gap_ms=0, dry=False,
                schedule_time="", check_limits=False)

    assert len(deliverer.calls) == 1


def test_a_broken_registry_lookup_does_not_drop_the_prompt():
    class Boom:
        def discover(self, now=None):
            raise RuntimeError("db locked")

    reports = []
    deliverer = FakeDeliverer([DeliveryResult(True, "sent", confirmed=True)])
    worker = SendWorker(deliverer, reports.append, Boom())

    worker._run([(session(), PromptItem(text="gg"), 1)], gap_ms=0, dry=False,
                schedule_time="", check_limits=False)

    assert len(deliverer.calls) == 1, "a failed lookup is not proof of death"


def test_mixed_run_counts_only_confirmed():
    reports, _, _ = run([
        DeliveryResult(True, "sent", confirmed=True),
        DeliveryResult(True, "sent, but the session showed no activity yet"),
        DeliveryResult(True, "sent", confirmed=True),
    ])
    sent, reason = done_args(reports)
    assert sent == 2
    assert "1 не подтверждено" in reason
