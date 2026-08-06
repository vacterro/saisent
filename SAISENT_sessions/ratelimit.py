"""Claude Code's rate limit, read from the record it actually writes.

`limits.scan_text` looks for prose -- "limit reached", "try again after" -- in
the transcript. Measured on 2026-08-06 across eight live transcripts: those
phrases appear **zero** times. The banner the user sees ("You've reached your
usage limit. Resets at 9:40 AM") is drawn by the desktop UI and never reaches
disk, which is why the quota panel cheerfully reported "свободен" while the
account was blocked.

What IS on disk, once per refusal, is a structured record:

    {"error":"rate_limit","isApiErrorMessage":true,"apiErrorStatus":429,
     "sessionId":"...","timestamp":"..."}

That is the signal: machine-readable, per session, stamped. No prose matching,
no guessing -- and the reset is then the rolling window measured from it.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Cheap pre-filter before paying for JSON parsing.
MARKER = re.compile(rb'"(?:error"\s*:\s*"rate_limit|apiErrorStatus"\s*:\s*429)')

# How far back a 429 still counts as "the limit is on". Claude's window is
# five hours; a refusal older than that belongs to a window already gone.
DEFAULT_WINDOW_HOURS = 5.0

# Only the tail of a transcript matters, and they grow into megabytes.
TAIL_BYTES = 256 * 1024


@dataclass
class RateLimitHit:
    when: datetime
    session_id: str = ""
    status: int = 429

    def reset_at(self, window_hours: float = DEFAULT_WINDOW_HOURS) -> datetime:
        return self.when + timedelta(hours=window_hours)


def _as_local(stamp: str) -> datetime | None:
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def scan_transcript(path: str | os.PathLike) -> RateLimitHit | None:
    """The newest rate-limit refusal in one transcript, or None."""
    file_path = Path(path)
    try:
        size = file_path.stat().st_size
        with open(file_path, "rb") as handle:
            handle.seek(max(0, size - TAIL_BYTES))
            blob = handle.read()
    except OSError:
        return None
    if not MARKER.search(blob):
        return None

    newest = None
    for raw in blob.split(b"\n"):
        if not MARKER.search(raw):
            continue
        try:
            record = json.loads(raw.decode("utf-8", "ignore"))
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        status = record.get("apiErrorStatus")
        if record.get("error") != "rate_limit" and status != 429:
            continue
        when = _as_local(str(record.get("timestamp") or ""))
        if when is None:
            continue
        hit = RateLimitHit(
            when=when,
            session_id=str(record.get("sessionId") or ""),
            status=int(status or 429),
        )
        if newest is None or hit.when > newest.when:
            newest = hit
    return newest


def scan_project_dir(
    projects_dir: str | os.PathLike,
    now: datetime | None = None,
    window_hours: float = DEFAULT_WINDOW_HOURS,
    max_files: int = 12,
) -> RateLimitHit | None:
    """The newest still-relevant refusal across recent transcripts.

    The limit is account-wide, so any session's 429 blocks all of them.
    """
    now = datetime.now() if now is None else now
    root = Path(projects_dir)
    try:
        files = sorted(
            root.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
        )[:max_files]
    except OSError:
        return None
    newest = None
    for path in files:
        hit = scan_transcript(path)
        if hit is None:
            continue
        if newest is None or hit.when > newest.when:
            newest = hit
    if newest is None:
        return None
    # A refusal older than the window belongs to a window that has passed.
    if newest.reset_at(window_hours) <= now:
        return None
    return newest
