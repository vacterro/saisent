"""SAISENT.log rotation (T-061).

The journal grows forever and the history panel re-parses the whole file each
open. `rotate_log` rolls the file at a size cap: the tail stays in the active
log, the older lines move to a dated archive, and `read_log` merges both so no
past run vanishes from the panel.
"""

from __future__ import annotations

import os

import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from SAISENT_sessions.history import (  # noqa: E402
    parse_log,
    read_log,
    rotate_log,
)

BATCH = "[2026-08-06 15:41:19] Отправляю 1 промпт(ов) в: wintage-c0. Когда: сейчас."
DELIVERY = "[2026-08-06 15:41:30] wintage-c0: OK (confirmed): agent typed it back"


def _write_lines(path, count, batch_every=5):
    lines = []
    for i in range(count):
        if i % batch_every == 0:
            lines.append(BATCH)
        lines.append(DELIVERY)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def test_small_log_never_rolls(tmp_path):
    path = tmp_path / "SAISENT.log"
    _write_lines(path, 10)
    assert rotate_log(path, cap_bytes=1_000_000) is False
    assert not list(tmp_path.glob("SAISENT.log.*"))


def test_past_cap_rolls_keeps_tail_and_archives_the_rest(tmp_path):
    path = tmp_path / "SAISENT.log"
    total = _write_lines(path, 400)  # plenty of bytes
    # Tiny cap forces a roll on the very next check.
    assert rotate_log(path, cap_bytes=100) is True

    archives = sorted(tmp_path.glob("SAISENT.log.*"))
    assert archives, "a dated archive must exist"
    archive_text = archives[0].read_text(encoding="utf-8")
    active_text = path.read_text(encoding="utf-8")
    # Everything that was in the file is still somewhere.
    assert len(archive_text.splitlines()) + len(active_text.splitlines()) == total
    assert DELIVERY in archive_text
    assert DELIVERY in active_text


def test_rotation_never_loses_a_run_from_the_panel(tmp_path):
    path = tmp_path / "SAISENT.log"
    _write_lines(path, 400)
    rotate_log(path, cap_bytes=100)

    runs, loose = read_log(path)
    # The batch-start lines in the archive and the active log must both be
    # found -- a run that predates the roll is not forgotten.
    all_deliveries = [d for run in runs for d in run.deliveries] + loose
    assert len(all_deliveries) == 400


def test_read_log_merges_archive_and_active_in_order(tmp_path):
    path = tmp_path / "SAISENT.log"
    path.write_text(BATCH + "\n" + DELIVERY + "\n", encoding="utf-8")
    rotate_log(path, cap_bytes=10)  # forces a roll

    # New activity lands in the active log after the roll.
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(BATCH + "\n" + DELIVERY + "\n")

    runs, _loose = read_log(path)
    assert len(runs) == 2
    assert all(len(run.deliveries) == 1 for run in runs)


def test_parse_log_still_handles_plain_text():
    runs, loose = parse_log(BATCH + "\n" + DELIVERY + "\n")
    assert len(runs) == 1
    assert len(runs[0].deliveries) == 1
