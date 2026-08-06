"""Quota state: cached, countable, and honest about what it does not know."""

from __future__ import annotations

from datetime import datetime, timedelta

from SAISENT_sessions.limitwatch import LimitMonitor, LimitReading, humanize


class FakeState:
    def __init__(self, reached=False, resets_at=None):
        self.reached = reached
        self.resets_at = resets_at


class FakeRegistry:
    def __init__(self, texts=None, boom=False):
        self.texts = texts or {}
        self.boom = boom
        self.calls = []

    def recent_transcripts(self, agent, *args, **kwargs):
        self.calls.append(agent)
        if self.boom:
            raise RuntimeError("disk on fire")
        return self.texts.get(agent, "")


NOW = datetime(2026, 8, 5, 9, 0, 0)


def monitor(registry, scan_text, ttl=60.0, ticks=None):
    clock = iter(ticks) if ticks else None
    return LimitMonitor(
        registry,
        scan_text,
        ttl=ttl,
        clock=(lambda: next(clock)) if clock else (lambda: 0.0),
    )


# --------------------------------------------------------------- LimitReading
def test_humanize_reads_like_a_countdown():
    assert humanize(45) == "45с"
    assert humanize(125) == "2м 05с"
    assert humanize(3900) == "1ч 05м"
    assert humanize(-5) == "0с"


def test_label_spells_out_the_reset_time_and_the_remainder():
    reading = LimitReading(
        agent="claude-code", reached=True, resets_at=NOW + timedelta(hours=1, minutes=5)
    )
    assert reading.label(NOW) == "до 10:05 (1ч 05м)"


def test_a_limit_with_no_named_time_says_so_instead_of_guessing():
    reading = LimitReading(agent="a", reached=True, resets_at=None)
    assert reading.label(NOW) == "ЛИМИТ, время сброса не названо"
    assert reading.seconds_left(NOW) is None
    # Nothing to count down to, so it still blocks -- guessing +5h here is
    # exactly the invented number the limits module refuses to produce.
    assert reading.blocking(NOW) is True


def test_a_passed_reset_time_stops_blocking():
    reading = LimitReading(
        agent="a", reached=True, resets_at=NOW - timedelta(minutes=1)
    )
    assert reading.clear_by_now(NOW) is True
    assert reading.blocking(NOW) is False
    assert "сброс уже прошёл" in reading.label(NOW)


def test_free_agent_reads_free():
    assert LimitReading(agent="a").label(NOW) == "свободен"
    assert LimitReading(agent="a").blocking(NOW) is False


# --------------------------------------------------------------- LimitMonitor
def test_scan_parses_the_agents_own_text():
    resets = NOW + timedelta(hours=2)
    registry = FakeRegistry({"claude-code": "limit reached"})
    mon = monitor(registry, lambda text: FakeState("limit reached" in text, resets))

    reading = mon.scan_agent("claude-code")

    assert reading.reached is True
    assert reading.resets_at == resets
    assert mon.reading("claude-code") is reading


def test_a_fresh_reading_is_not_rescanned():
    """Scanning opens twenty files; doing it per refresh is what froze the UI."""
    registry = FakeRegistry({"a": ""})
    mon = monitor(registry, lambda text: FakeState(False), ttl=60.0)

    mon.scan(["a"])
    mon.scan(["a"])
    mon.scan(["a"])

    assert registry.calls == ["a"]


def test_a_stale_reading_is_rescanned():
    registry = FakeRegistry({"a": ""})
    # Ticks in call order: the first scan stamps 0.0, the second staleness
    # check reads 100.0, and the rescan it triggers stamps 100.0 again.
    mon = monitor(registry, lambda text: FakeState(False), ttl=10.0,
                  ticks=[0.0, 100.0, 100.0])

    mon.scan(["a"])
    mon.scan(["a"])

    assert registry.calls == ["a", "a"]


def test_force_rescans_even_when_fresh():
    registry = FakeRegistry({"a": ""})
    mon = monitor(registry, lambda text: FakeState(False))

    mon.scan(["a"])
    mon.scan(["a"], force=True)

    assert registry.calls == ["a", "a"]


def test_a_reading_whose_reset_time_arrived_is_stale_whatever_the_ttl_says():
    registry = FakeRegistry({"a": "limit reached"})
    mon = monitor(
        registry, lambda text: FakeState(True, NOW - timedelta(seconds=1)), ttl=9999.0
    )
    mon.scan(["a"], now=NOW)

    assert mon.stale("a", now=NOW) is True
    mon.scan(["a"], now=NOW)
    assert registry.calls == ["a", "a"]


def test_a_broken_transcript_read_is_an_error_reading_not_a_crash():
    mon = monitor(FakeRegistry(boom=True), lambda text: FakeState(False))
    reading = mon.scan_agent("a")

    assert reading.error == "disk on fire"
    assert reading.reached is False
    assert "нет данных" in reading.label(NOW)


def test_a_throwing_parser_is_an_error_reading_too():
    def boom(_text):
        raise ValueError("bad regex")

    reading = monitor(FakeRegistry({"a": "x"}), boom).scan_agent("a")
    assert "bad regex" in reading.error


def test_blocking_agents_lists_only_the_ones_still_held():
    registry = FakeRegistry({"a": "", "b": ""})
    states = {
        "a": FakeState(True, NOW + timedelta(hours=1)),
        "b": FakeState(True, NOW - timedelta(hours=1)),
    }
    mon = LimitMonitor(registry, lambda text: states.pop(next(iter(states))),
                       clock=lambda: 0.0)
    mon.scan_agent("a", now=NOW)
    mon.scan_agent("b", now=NOW)

    assert mon.blocking_agents(now=NOW) == ["a"]


def test_summary_names_the_agent_that_frees_up_first():
    registry = FakeRegistry()
    mon = LimitMonitor(registry, lambda text: FakeState(False), clock=lambda: 0.0)
    mon._readings = {
        "slow": LimitReading("slow", True, NOW + timedelta(hours=4)),
        "soon": LimitReading("soon", True, NOW + timedelta(minutes=3)),
    }
    assert mon.summary(NOW).startswith("soon: до 09:03")


def test_a_plan_fills_a_reset_time_the_agent_never_named():
    """Freebuff never states a time; without the rule it blocks with no clock."""
    mon = LimitMonitor(FakeRegistry(), lambda t: FakeState(True), clock=lambda: 0.0)
    mon._readings = {"freebuff": LimitReading("freebuff", reached=True)}

    patched = mon.apply_plan("freebuff")

    assert patched.resets_at is not None
    assert patched.resets_at.hour == 10 and patched.resets_at.minute == 0


def test_a_plan_never_overwrites_a_time_the_agent_stated():
    stated = datetime(2030, 1, 1, 1, 1)
    mon = LimitMonitor(FakeRegistry(), lambda t: FakeState(True), clock=lambda: 0.0)
    mon._readings = {"freebuff": LimitReading("freebuff", True, stated)}

    assert mon.apply_plan("freebuff").resets_at == stated


def test_a_plan_is_not_applied_to_an_agent_that_is_free():
    mon = LimitMonitor(FakeRegistry(), lambda t: FakeState(False), clock=lambda: 0.0)
    mon._readings = {"freebuff": LimitReading("freebuff", reached=False)}

    assert mon.apply_plan("freebuff").resets_at is None


def test_claude_gets_five_hours_from_its_last_send():
    last = datetime.now() - timedelta(hours=1)
    mon = LimitMonitor(FakeRegistry(), lambda t: FakeState(True), clock=lambda: 0.0)
    mon._readings = {"claude-code": LimitReading("claude-code", reached=True)}

    patched = mon.apply_plan("claude-code", last_send=last)

    assert patched.resets_at is not None
    left = patched.seconds_left(datetime.now())
    assert 3 * 3600 < left <= 4 * 3600 + 60


def test_summary_when_nothing_is_blocked():
    mon = LimitMonitor(FakeRegistry(), lambda text: FakeState(False),
                       clock=lambda: 0.0)
    assert mon.summary(NOW) == "лимиты не проверялись"

    mon._readings = {"a": LimitReading("a")}
    assert mon.summary(NOW) == "лимиты: все агенты свободны"
