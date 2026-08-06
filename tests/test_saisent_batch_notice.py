"""T-059: a finished batch must announce itself, not sit silent.

The worker's done event carries `(sent, reason)` where the reason already
names the trouble. `batch_done_notice` turns that into what the UI should
show: a quiet info balloon for a clean run, a warning balloon plus a bell
when something failed, and nothing at all for a stopped batch (the user
stopped it themselves).

Pure on purpose: the whole matrix is testable without a window or a tray.
"""

from __future__ import annotations

from SAISENT import batch_done_notice


def test_a_clean_batch_gets_a_quiet_info_balloon():
    notice = batch_done_notice(3, "готово")
    assert notice == ("SAISENT — готово", "Отправлено 3: готово", False)


def test_a_batch_with_failures_gets_a_warning_and_bell():
    notice = batch_done_notice(2, "готово, 1 с ошибкой — в очереди")
    assert notice[0] == "SAISENT — не всё отправлено"
    assert "1 с ошибкой" in notice[1]
    assert notice[2] is True


def test_unconfirmed_sends_warn_too():
    notice = batch_done_notice(1, "готово, 1 не подтверждено — в очереди")
    assert notice[2] is True


def test_skipped_sessions_warn_too():
    notice = batch_done_notice(0, "готово, 2 пропущено (сессии нет) — в очереди")
    assert notice[2] is True


def test_a_crash_warns():
    notice = batch_done_notice(0, "сбой: окно не найдено")
    assert notice[2] is True


def test_a_stopped_batch_announces_nothing():
    assert batch_done_notice(1, "остановлено") is None


def test_empty_reason_announces_nothing():
    assert batch_done_notice(0, "") is None
