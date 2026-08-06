"""Per-agent reset rules: fill the silence, never argue with the agent."""

from __future__ import annotations

from datetime import datetime, timedelta

from SAISENT_sessions import quota_plan as qp

NOW = datetime(2026, 8, 6, 9, 0, 0)


# ------------------------------------------------------------------ parsing
def test_daily_is_parsed():
    plan = qp.parse("daily 10:00")
    assert (plan.kind, plan.hour, plan.minute) == (qp.DAILY, 10, 0)


def test_rolling_is_parsed():
    plan = qp.parse("rolling 5h")
    assert (plan.kind, plan.hours) == (qp.ROLLING, 5.0)
    assert qp.parse("rolling 1.5h").hours == 1.5


def test_nonsense_falls_back_to_the_agents_own_words():
    for spec in ("", "text", "whenever", "daily 99:00", "rolling 0h", "daily 10"):
        assert qp.parse(spec).kind == qp.TEXT, spec


# ---------------------------------------------------------------- next reset
def test_daily_before_the_hour_is_today():
    plan = qp.parse("daily 10:00")
    assert plan.next_reset(NOW) == datetime(2026, 8, 6, 10, 0)


def test_daily_after_the_hour_rolls_to_tomorrow():
    plan = qp.parse("daily 03:00")
    assert plan.next_reset(NOW) == datetime(2026, 8, 7, 3, 0)


def test_daily_exactly_on_the_hour_means_the_next_one():
    """At 10:00:00 sharp the window that ends now is not the one we wait for."""
    plan = qp.parse("daily 10:00")
    assert plan.next_reset(datetime(2026, 8, 6, 10, 0)) == datetime(2026, 8, 7, 10, 0)


def test_rolling_counts_from_the_last_send():
    plan = qp.parse("rolling 5h")
    last = datetime(2026, 8, 6, 7, 30)
    assert plan.next_reset(NOW, last) == datetime(2026, 8, 6, 12, 30)


def test_rolling_without_a_send_has_no_window_to_count_from():
    assert qp.parse("rolling 5h").next_reset(NOW, None) is None


def test_a_text_plan_predicts_nothing():
    assert qp.parse("text").next_reset(NOW, NOW) is None


# --------------------------------------------------------------- the defaults
def test_the_shipped_defaults_match_what_the_user_observes():
    assert qp.plan_for("freebuff").next_reset(NOW) == datetime(2026, 8, 6, 10, 0)
    assert qp.plan_for("codenomad").next_reset(NOW) == datetime(2026, 8, 7, 3, 0)
    claude = qp.plan_for("claude-code")
    assert claude.kind == qp.ROLLING and claude.hours == 5.0
    assert qp.plan_for("antigravity").kind == qp.TEXT


def test_an_override_replaces_a_default():
    plan = qp.plan_for("freebuff", {"freebuff": "daily 06:30"})
    assert plan.next_reset(NOW) == datetime(2026, 8, 6, 6, 30) + timedelta(days=1)


def test_an_unknown_agent_is_a_text_plan():
    assert qp.plan_for("mystery").kind == qp.TEXT


# ------------------------------------------------------------ predicted_reset
def test_a_time_the_agent_stated_always_wins():
    """A rule we invented must never overrule the agent's own words."""
    stated = datetime(2026, 8, 6, 11, 11)
    when, source = qp.predicted_reset("freebuff", NOW, stated=stated)

    assert when == stated
    assert source == "агент назвал"


def test_the_rule_fills_the_silence():
    when, source = qp.predicted_reset("codenomad", NOW)
    assert when == datetime(2026, 8, 7, 3, 0)
    assert "каждый день в 03:00" in source


def test_claude_predicts_five_hours_from_the_last_prompt():
    last = datetime(2026, 8, 6, 4, 0)
    when, source = qp.predicted_reset("claude-code", NOW, last_send=last)

    assert when == datetime(2026, 8, 6, 9, 0)
    assert "через 5ч после отправки" == source


def test_no_rule_and_no_words_predicts_nothing():
    when, source = qp.predicted_reset("antigravity", NOW)
    assert when is None
    assert source == "по словам агента"


def test_describe_reads_like_a_sentence():
    assert qp.parse("daily 10:00").describe() == "каждый день в 10:00"
    assert qp.parse("rolling 5h").describe() == "через 5ч после отправки"
    assert qp.parse("rolling 1.5h").describe() == "через 1.5ч после отправки"
