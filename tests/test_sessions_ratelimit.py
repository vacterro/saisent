"""Claude's 429 record: the only limit signal that actually reaches disk."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from SAISENT_sessions import ratelimit

NOW = datetime(2026, 8, 6, 9, 0, 0)


def line(**over):
    record = {
        "requestId": "req_1",
        "error": "rate_limit",
        "isApiErrorMessage": True,
        "apiErrorStatus": 429,
        "userType": "external",
        "entrypoint": "claude-desktop",
        "sessionId": "sess-1",
        "timestamp": "2026-08-06T08:30:00.000Z",
    }
    record.update(over)
    return json.dumps(record)


def write(path, *lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def local(stamp: str) -> datetime:
    return ratelimit._as_local(stamp)


def test_a_429_record_is_found():
    path_stamp = "2026-08-06T08:30:00.000Z"
    assert local(path_stamp) is not None


def test_the_refusal_is_read_out_of_a_transcript(tmp_path):
    path = write(tmp_path / "p" / "s.jsonl", '{"type":"user"}', line())

    hit = ratelimit.scan_transcript(path)

    assert hit is not None
    assert hit.status == 429
    assert hit.session_id == "sess-1"


def test_prose_is_not_needed_and_not_used(tmp_path):
    """Measured: 'limit reached' never appears in a real transcript."""
    path = write(tmp_path / "p" / "s.jsonl", '{"text":"limit reached, sorry"}')
    assert ratelimit.scan_transcript(path) is None


def test_the_newest_refusal_wins(tmp_path):
    path = write(
        tmp_path / "p" / "s.jsonl",
        line(timestamp="2026-08-06T05:00:00.000Z"),
        line(timestamp="2026-08-06T08:45:00.000Z"),
        line(timestamp="2026-08-06T07:00:00.000Z"),
    )

    hit = ratelimit.scan_transcript(path)
    assert hit.when == local("2026-08-06T08:45:00.000Z")


def test_a_clean_transcript_yields_nothing(tmp_path):
    path = write(tmp_path / "p" / "s.jsonl", '{"type":"assistant"}')
    assert ratelimit.scan_transcript(path) is None


def test_a_missing_file_is_not_an_error(tmp_path):
    assert ratelimit.scan_transcript(tmp_path / "nope.jsonl") is None


def test_broken_json_lines_are_skipped(tmp_path):
    path = write(tmp_path / "p" / "s.jsonl", '{"error":"rate_limit" oops', line())
    assert ratelimit.scan_transcript(path) is not None


def test_a_record_without_a_timestamp_is_useless(tmp_path):
    path = write(tmp_path / "p" / "s.jsonl", line(timestamp=""))
    assert ratelimit.scan_transcript(path) is None


def test_reset_is_the_rolling_window_from_the_refusal():
    hit = ratelimit.RateLimitHit(when=datetime(2026, 8, 6, 5, 30))
    assert hit.reset_at(5.0) == datetime(2026, 8, 6, 10, 30)


# ------------------------------------------------------------- project sweep
def test_the_limit_is_account_wide_so_any_session_counts(tmp_path):
    write(tmp_path / "a" / "one.jsonl", '{"type":"user"}')
    write(tmp_path / "b" / "two.jsonl", line(timestamp="2026-08-06T08:30:00.000Z"))

    hit = ratelimit.scan_project_dir(tmp_path, now=NOW)

    assert hit is not None
    assert hit.session_id == "sess-1"


def test_a_refusal_older_than_the_window_no_longer_blocks(tmp_path):
    write(tmp_path / "a" / "one.jsonl", line(timestamp="2026-08-06T01:00:00.000Z"))

    assert ratelimit.scan_project_dir(tmp_path, now=NOW, window_hours=5.0) is None


def test_a_refusal_inside_the_window_still_blocks(tmp_path):
    write(tmp_path / "a" / "one.jsonl", line(timestamp="2026-08-06T06:00:00.000Z"))

    hit = ratelimit.scan_project_dir(tmp_path, now=NOW, window_hours=5.0)
    assert hit is not None
    assert hit.reset_at(5.0) == local("2026-08-06T06:00:00.000Z") + timedelta(hours=5)


def test_a_missing_projects_dir_is_not_an_error(tmp_path):
    assert ratelimit.scan_project_dir(tmp_path / "nope", now=NOW) is None
