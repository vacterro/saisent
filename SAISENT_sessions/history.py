"""Send-history: parse SAISENT.log into deliveries with verdicts.

T-049: a journal view of past deliveries, sourced from SAISENT.log -- the
single ledger the app already writes -- rather than a second store that could
drift. The worker logs one line per delivery:

    [2026-08-06 15:41:30] wintage-c0: OK (unconfirmed): sent, but the session
                                                       showed no activity yet
    [2026-08-06 15:42:10] saipenview-50: FAIL (unconfirmed): reason
    [2026-08-06 15:42:37] saisent-1a: пропущен — сессия закрылась

and one line per batch start that opens a run:

    [2026-08-06 15:41:19] Отправляю 1 промпт(ов) в: wintage-c0. Когда: сейчас.

The verdicts map onto the queue's own honesty: `OK (confirmed)` means the
session really moved (sent), `OK (unconfirmed)` means keys went out but the
session showed no activity (stays in queue), `FAIL` is a refusal/error, and a
`пропущен` line means the session died before its prompt went.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SENT = "sent"
UNCONFIRMED = "unconfirmed"
FAILED = "failed"
SKIPPED = "skipped"

VERDICTS = (SENT, UNCONFIRMED, FAILED, SKIPPED)

VERDICT_LABELS = {
    SENT: "ушло",
    UNCONFIRMED: "не подтверждено",
    FAILED: "ошибка",
    SKIPPED: "пропущено",
}

_RUN_RE = re.compile(
    r"^Отправляю (\d+) промпт\(ов\) в: (.+?)\. Когда: (.+?)\.$"
)
_DELIVERY_RE = re.compile(
    r"^(?P<name>[^:]+): (?P<mark>OK|FAIL) "
    r"\((?P<seal>confirmed|unconfirmed)\): (?P<reason>.*)$"
)
_SKIP_RE = re.compile(r"^(?P<name>[^:]+): пропущен — (?P<reason>.*)$")


@dataclass
class Delivery:
    """One delivery line from the log, with its verdict."""

    at: str  # "2026-08-06 15:41:30"
    name: str
    verdict: str
    reason: str
    run: int = 0  # 0 = before any batch-start line


@dataclass
class Run:
    """One batch attempt: the 'Отправляю N промпт(ов) в: ...' line and its
    deliveries, with the per-verdict tally."""

    at: str
    count: int
    names: str
    when: str
    deliveries: list[Delivery] = field(default_factory=list)

    @property
    def tally(self) -> dict[str, int]:
        out = {v: 0 for v in VERDICTS}
        for d in self.deliveries:
            out[d.verdict] += 1
        return out

    @property
    def total(self) -> int:
        return len(self.deliveries)


def parse_log(text: str) -> tuple[list[Run], list[Delivery]]:
    """Parse SAISENT.log text into runs + ungrouped deliveries.

    A batch-start line opens a run; every delivery that follows belongs to it
    until the next batch-start line. Deliveries that appear with no batch
    context (e.g. the app start line) land in the ungrouped list.
    """
    runs: list[Run] = []
    loose: list[Delivery] = []
    current: Run | None = None

    for line in text.splitlines():
        line = line.rstrip("\r")
        if not line:
            continue
        # [stamp] message
        if not line.startswith("["):
            continue
        close = line.find("]")
        if close < 0:
            continue
        at = line[1:close].strip()
        message = line[close + 1 :].strip()

        m = _RUN_RE.match(message)
        if m:
            current = Run(
                at=at, count=int(m.group(1)), names=m.group(2), when=m.group(3)
            )
            runs.append(current)
            continue

        dm = _DELIVERY_RE.match(message)
        if dm:
            name = dm.group("name")
            mark = dm.group("mark")
            seal = dm.group("seal")
            reason = dm.group("reason")
            if mark == "OK" and seal == "confirmed":
                verdict = SENT
            elif mark == "OK":
                verdict = UNCONFIRMED
            else:
                verdict = FAILED
            delivery = Delivery(at=at, name=name, verdict=verdict, reason=reason)
            if current is not None:
                current.deliveries.append(delivery)
            else:
                loose.append(delivery)
            continue

        sm = _SKIP_RE.match(message)
        if sm:
            delivery = Delivery(
                at=at,
                name=sm.group("name"),
                verdict=SKIPPED,
                reason=sm.group("reason"),
            )
            if current is not None:
                current.deliveries.append(delivery)
            else:
                loose.append(delivery)

    return runs, loose


DEFAULT_CAP_BYTES = 1_000_000  # 1 MB of journal is plenty for a season


def _archive_paths(path) -> list[str]:
    """Sibling `SAISENT.log.YYYYMMDD` archives, oldest first.

    The rotation keeps the tail in the active log and moves the older lines
    to a dated archive; the panel reads both so no past run vanishes.
    """
    import os

    base = str(path)
    parent = os.path.dirname(base) or "."
    name = os.path.basename(base)
    prefix = name + "."
    try:
        entries = sorted(os.listdir(parent))
    except OSError:
        return []
    out = []
    for entry in entries:
        if not entry.startswith(prefix):
            continue
        stamp = entry[len(prefix):]
        if len(stamp) == 8 and stamp.isdigit():
            out.append(os.path.join(parent, entry))
    return out


def rotate_log(path, cap_bytes: int = DEFAULT_CAP_BYTES) -> bool:
    """Roll `SAISENT.log` when it passes `cap_bytes`: keep the tail in the
    active log, append the older lines to a dated archive.

    Returns True when a roll happened. Cheap when small -- one stat, no read
    -- so `log()` can call it on every write without measuring anything.
    """
    import os

    try:
        size = os.path.getsize(path)
    except OSError:
        return False
    if size <= cap_bytes:
        return False
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return False
    if len(lines) <= 1:
        return False
    # Keep a bounded tail in the active log (at most half the cap, at least
    # a few hundred lines so the last runs stay openable by hand).
    keep = max(200, min(len(lines) // 2, 5000))
    older, tail = lines[:-keep], lines[-keep:]
    if not older:
        return False
    from datetime import datetime

    stamp = datetime.now().strftime("%Y%m%d")
    archive = os.path.join(os.path.dirname(str(path)) or ".",
                           os.path.basename(str(path)) + "." + stamp)
    try:
        with open(archive, "a", encoding="utf-8") as handle:
            handle.write("\n".join(older) + "\n")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(tail) + "\n")
    except OSError:
        return False
    return True


def read_log(path) -> tuple[list[Run], list[Delivery]]:
    """Read the log file (any file-like path or str) and parse it.

    Reads the dated archives first, then the active log, so rotation never
    hides a past run from the panel.
    """
    def read_one(target) -> str:
        if hasattr(target, "read_text"):
            try:
                return target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return ""
        try:
            with open(target, encoding="utf-8", errors="replace") as handle:
                return handle.read()
        except OSError:
            return ""

    texts = [read_one(p) for p in _archive_paths(path)]
    texts.append(read_one(path))
    return parse_log("\n".join(texts))
