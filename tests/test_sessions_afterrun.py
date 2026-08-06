"""Post-run machine actions: safe by default, honest about the unsafe ones."""

from __future__ import annotations

import pytest

from SAISENT_sessions import afterrun


def test_nothing_is_the_default_and_does_nothing():
    ran, message = afterrun.run_after(afterrun.NOTHING)
    assert ran is False
    assert message == ""

    ran, message = afterrun.run_after("")
    assert ran is False


def test_monitor_off_runs_its_handler():
    called = []
    ran, message = afterrun.run_after(
        afterrun.MONITOR_OFF, handlers={afterrun.MONITOR_OFF: lambda: called.append(1)}
    )

    assert ran is True
    assert called == [1]
    assert "погасить экран" in message


def test_a_failing_action_never_turns_a_good_send_into_an_error():
    def boom():
        raise OSError("display refused")

    ran, message = afterrun.run_after(
        afterrun.MONITOR_OFF, handlers={afterrun.MONITOR_OFF: boom}
    )

    assert ran is False
    assert "не вышло" in message
    assert "display refused" in message


def test_an_unknown_action_is_reported_not_executed():
    ran, message = afterrun.run_after("self_destruct", handlers={})
    assert ran is False
    assert "неизвестное действие" in message


def test_monitor_off_carries_no_warning_because_it_is_the_safe_one():
    """It leaves the session unlocked, so a later batch can still type."""
    assert afterrun.warning_for(afterrun.MONITOR_OFF) == ""


@pytest.mark.parametrize("key", [afterrun.LOCK, afterrun.SLEEP])
def test_the_dangerous_actions_say_what_they_break(key):
    warning = afterrun.warning_for(key)
    assert warning, f"{key} must warn before it is chosen"


def test_lock_warns_specifically_about_keystroke_delivery():
    assert "отладчик" in afterrun.warning_for(afterrun.LOCK)


def test_sleep_warns_that_the_schedule_will_not_fire():
    assert "расписание" in afterrun.warning_for(afterrun.SLEEP)


def test_labels_round_trip():
    for action in afterrun.ACTIONS:
        assert afterrun.key_for(action.label) == action.key
        assert afterrun.label_for(action.key) == action.label


def test_an_unknown_label_falls_back_to_nothing():
    assert afterrun.key_for("выключить дом") == afterrun.NOTHING
    assert afterrun.label_for("bogus") == "ничего"
