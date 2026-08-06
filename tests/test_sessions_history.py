"""Send-history parser: deliveries from SAISENT.log with honest verdicts.

T-049's source of truth is the log the worker already writes -- one line per
delivery (`name: OK (confirmed): reason` / `OK (unconfirmed)` / `FAIL`), one
line per skipped session (`name: пропущен — reason`), and one batch-start line
per run (`Отправляю N промпт(ов) в: ... Когда: ...`). These tests pin the
parser against real log shapes so the panel can never invent a verdict.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from SAISENT_sessions.history import (  # noqa: E402
    FAILED,
    SENT,
    SKIPPED,
    UNCONFIRMED,
    parse_log,
)

SAMPLE = """\
[2026-08-06 05:30:36] saisent-97: OK (unconfirmed): dry run: nothing sent
[2026-08-06 05:30:36] Пробный прогон — машину не трогаем.
[2026-08-06 15:39:55] SAISENT 4.0.0 запущен.
[2026-08-06 15:41:19] Отправляю 1 промпт(ов) в: wintage-c0. Когда: сейчас.
[2026-08-06 15:41:30] wintage-c0: OK (unconfirmed): sent, but the session showed no activity yet
[2026-08-06 15:41:48] Отправляю 2 промпт(ов) в: saisent-1a, wintage-c0. Когда: 19:51.
[2026-08-06 15:41:58] saisent-1a: OK (confirmed): agent typed it back
[2026-08-06 15:41:59] wintage-c0: FAIL (unconfirmed): quota block
[2026-08-06 15:42:10] saisent-1a: пропущен — сессия закрылась, пока промпт ждал
"""


def test_parse_log_groups_runs_and_verdicts():
    runs, loose = parse_log(SAMPLE)

    # Two batch-start lines -> two runs.
    assert len(runs) == 2
    assert runs[0].count == 1
    assert runs[0].names == "wintage-c0"
    assert runs[0].when == "сейчас"
    assert runs[1].count == 2
    assert runs[1].when == "19:51"

    # Run 1: one unconfirmed delivery.
    assert len(runs[0].deliveries) == 1
    d = runs[0].deliveries[0]
    assert d.name == "wintage-c0"
    assert d.verdict == UNCONFIRMED

    # Run 2: confirmed -> sent, FAIL -> failed, пропущен -> skipped.
    assert [d.verdict for d in runs[1].deliveries] == [SENT, FAILED, SKIPPED]
    tally = runs[1].tally
    assert tally == {SENT: 1, UNCONFIRMED: 0, FAILED: 1, SKIPPED: 1}


def test_parse_log_loose_deliveries_before_any_run():
    runs, loose = parse_log(SAMPLE)
    # The dry-run line appears before any batch-start line -> loose.
    assert len(loose) == 1
    assert loose[0].name == "saisent-97"
    assert loose[0].verdict == UNCONFIRMED


def test_parse_log_ignores_non_delivery_lines():
    runs, loose = parse_log(SAMPLE)
    # Startup and «Пробный прогон» lines produce no entries.
    assert not [d for d in loose if d.name == "SAISENT"]
    assert not [d for r in runs for d in r.deliveries if d.name == "SAISENT"]


def test_parse_log_empty_and_garbage():
    assert parse_log("") == ([], [])
    runs, loose = parse_log("not a log line\n[broken\n[2026-08-06 15:41:30] тоже не доставка\n")
    assert runs == []
    assert loose == []
