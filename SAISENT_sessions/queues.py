"""One ordered prompt queue per session, durable across restarts.

The old console had a single global list of macro steps, so "send this to the
saipen session and that to the saisent one" was not expressible -- you rewrote
the steps between runs. Here every session key owns its own ordered list, the
order IS the send order, and the file on disk is the truth: a crash mid-run
loses nothing that was already added.

Item state is deliberately explicit (`pending` / `sending` / `sent` / `failed`)
rather than "still in the list means unsent". A sent prompt that vanishes from
the pane is indistinguishable from one that was never added.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

STATE_PENDING = "pending"
STATE_SENDING = "sending"
STATE_SENT = "sent"
STATE_FAILED = "failed"

ACTIVE_STATES = (STATE_PENDING, STATE_FAILED)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class PromptItem:
    """One prompt waiting for one session."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    text: str = ""
    state: str = STATE_PENDING
    created: str = field(default_factory=_now_iso)
    sent_at: str = ""
    reason: str = ""
    # Whether the session's own store moved after this prompt. "Sent" only
    # means the keystrokes went out; this is the part that says it landed.
    confirmed: bool = False

    @property
    def label(self) -> str:
        """One line of the prompt, for a list that has one row per item."""
        flat = " ".join(self.text.split())
        return flat if len(flat) <= 90 else flat[:87] + "..."

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw) -> "PromptItem | None":
        if not isinstance(raw, dict):
            return None
        text = raw.get("text")
        if not isinstance(text, str) or not text.strip():
            return None
        item = cls(
            id=str(raw.get("id") or uuid.uuid4().hex[:12]),
            text=text,
            state=str(raw.get("state") or STATE_PENDING),
            created=str(raw.get("created") or _now_iso()),
            sent_at=str(raw.get("sent_at") or ""),
            reason=str(raw.get("reason") or ""),
            confirmed=bool(raw.get("confirmed")),
        )
        if item.state not in (STATE_PENDING, STATE_SENDING, STATE_SENT, STATE_FAILED):
            item.state = STATE_PENDING
        # `sending` is never a resting state: a process that died mid-send left
        # it there, and on reload the item is simply pending again.
        if item.state == STATE_SENDING:
            item.state = STATE_PENDING
        return item


class QueueStore:
    """Every session's queue, keyed by `Session.key`."""

    version = 1

    def __init__(self, path: str | os.PathLike) -> None:
        self.path = Path(path)
        self.queues: dict[str, list[PromptItem]] = {}
        self.labels: dict[str, str] = {}
        # A session key may name its own HH:MM instead of inheriting the
        # global schedule_time, so two sessions can fire at different times
        # in one night. Empty/absent means "inherit the global time".
        self.schedules: dict[str, str] = {}

    # ---- reading -----------------------------------------------------
    def items(self, key: str) -> list[PromptItem]:
        return list(self.queues.get(key, ()))

    def pending(self, key: str) -> list[PromptItem]:
        return [i for i in self.queues.get(key, ()) if i.state in ACTIVE_STATES]

    def next_pending(self, key: str) -> PromptItem | None:
        for item in self.queues.get(key, ()):
            if item.state in ACTIVE_STATES:
                return item
        return None

    def find(self, key: str, item_id: str) -> PromptItem | None:
        for item in self.queues.get(key, ()):
            if item.id == item_id:
                return item
        return None

    def schedule_of(self, key: str) -> str:
        """The session's own HH:MM, or "" when it inherits the global time."""
        return self.schedules.get(key, "")

    def set_schedule(self, key: str, hhmm: str) -> None:
        """Set (or clear, on "") a session's own send time. No validation
        here -- the UI owns the HH:MM shape; this store just remembers."""
        hhmm = (hhmm or "").strip()
        if hhmm:
            self.schedules[key] = hhmm
        else:
            self.schedules.pop(key, None)

    def keys_with_pending(self) -> list[str]:
        return [key for key in self.queues if self.pending(key)]

    def total_pending(self) -> int:
        return sum(len(self.pending(key)) for key in self.queues)

    # ---- writing -----------------------------------------------------
    def add(self, key: str, text: str, label: str = "") -> PromptItem | None:
        if not key or not text.strip():
            return None
        item = PromptItem(text=text)
        self.queues.setdefault(key, []).append(item)
        if label:
            self.labels[key] = label
        return item

    def remove(self, key: str, item_id: str) -> bool:
        items = self.queues.get(key)
        if not items:
            return False
        for index, item in enumerate(items):
            if item.id == item_id:
                del items[index]
                return True
        return False

    def clear(self, key: str) -> int:
        removed = len(self.queues.get(key, ()))
        self.queues.pop(key, None)
        return removed

    def clear_finished(self, key: str) -> int:
        items = self.queues.get(key)
        if not items:
            return 0
        keep = [i for i in items if i.state in ACTIVE_STATES]
        removed = len(items) - len(keep)
        self.queues[key] = keep
        return removed

    def clear_all_queues(self) -> int:
        """Completely empties all queues across all sessions."""
        total = sum(len(items) for items in self.queues.values())
        self.queues.clear()
        return total

    def move(self, key: str, item_id: str, delta: int) -> bool:
        """Shift one item by `delta` places, clamped to the list."""
        items = self.queues.get(key)
        if not items or not delta:
            return False
        for index, item in enumerate(items):
            if item.id == item_id:
                target = max(0, min(len(items) - 1, index + delta))
                if target == index:
                    return False
                items.insert(target, items.pop(index))
                return True
        return False

    def move_to(self, key: str, item_id: str, position: int) -> bool:
        """Drop one item at an absolute position -- what a drag produces."""
        items = self.queues.get(key)
        if not items:
            return False
        for index, item in enumerate(items):
            if item.id == item_id:
                target = max(0, min(len(items) - 1, position))
                if target == index:
                    return False
                items.insert(target, items.pop(index))
                return True
        return False

    def edit(self, key: str, item_id: str, text: str) -> bool:
        """Rewrite a queued prompt in place, keeping its position.

        An edited item goes back to `pending` whatever it was: the text that
        was sent is no longer the text in the row, so leaving it marked `sent`
        would be a lie about what the session received.
        """
        if not text.strip():
            return False
        item = self.find(key, item_id)
        if item is None or item.text == text:
            return False
        item.text = text
        item.state = STATE_PENDING
        item.reason = ""
        item.sent_at = ""
        return True

    def duplicate(self, key: str, item_id: str) -> PromptItem | None:
        """Copy an item directly below itself, as a fresh pending prompt."""
        items = self.queues.get(key)
        if not items:
            return None
        for index, item in enumerate(items):
            if item.id == item_id:
                clone = PromptItem(text=item.text)
                items.insert(index + 1, clone)
                return clone
        return None

    def mark(
        self,
        key: str,
        item_id: str,
        state: str,
        reason: str = "",
        confirmed: bool = False,
    ) -> bool:
        item = self.find(key, item_id)
        if item is None:
            return False
        item.state = state
        item.reason = reason
        item.confirmed = bool(confirmed)
        if state == STATE_SENT:
            item.sent_at = _now_iso()
        return True

    def counts(self, key: str) -> dict:
        """How this queue stands, for a line the user can read at a glance."""
        tally = {
            STATE_PENDING: 0,
            STATE_SENT: 0,
            STATE_FAILED: 0,
            "confirmed": 0,
            "total": 0,
        }
        for item in self.queues.get(key, ()):
            tally["total"] += 1
            if item.state == STATE_SENDING:
                tally[STATE_PENDING] += 1
            elif item.state in tally:
                tally[item.state] += 1
            if item.state == STATE_SENT and item.confirmed:
                tally["confirmed"] += 1
        return tally

    def requeue_all(self, key: str) -> int:
        """Put every finished item back in line -- the 'send it again' button."""
        count = 0
        for item in self.queues.get(key, ()):
            if item.state in (STATE_SENT, STATE_FAILED):
                item.state = STATE_PENDING
                item.reason = ""
                item.sent_at = ""
                count += 1
        return count

    def prune(self, live_keys) -> list[str]:
        """Forget queues whose session is gone AND which have nothing pending.

        Pending work is never dropped on the strength of a session being
        offline: agents get restarted, and a queue that silently empties itself
        while the user was closing a tab is the worst possible behaviour for a
        durable store.
        """
        live = set(live_keys)
        dropped = []
        for key in list(self.queues):
            if key in live:
                continue
            if self.pending(key):
                continue
            self.queues.pop(key, None)
            self.labels.pop(key, None)
            dropped.append(key)
        return dropped

    # ---- persistence -------------------------------------------------
    def load(self) -> bool:
        if not self.path.exists():
            return False
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if not isinstance(raw, dict):
            return False
        queues: dict[str, list[PromptItem]] = {}
        for key, entries in (raw.get("queues") or {}).items():
            if not isinstance(entries, list):
                continue
            items = [PromptItem.from_dict(entry) for entry in entries]
            items = [item for item in items if item is not None]
            if items:
                queues[str(key)] = items
        self.queues = queues
        labels = raw.get("labels")
        self.labels = (
            {str(k): str(v) for k, v in labels.items()}
            if isinstance(labels, dict)
            else {}
        )
        schedules = raw.get("schedules")
        self.schedules = (
            {str(k): str(v) for k, v in schedules.items() if v}
            if isinstance(schedules, dict)
            else {}
        )
        return True

    def save(self) -> bool:
        payload = {
            "version": self.version,
            "labels": self.labels,
            "schedules": dict(self.schedules),
            "queues": {
                key: [item.to_dict() for item in items]
                for key, items in self.queues.items()
                if items
            },
        }
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(temp, self.path)
        except OSError:
            return False
        return True

    def export_jsonl(self, path: str | os.PathLike) -> int:
        """Write every item to a portable JSONL file, one line per item.

        The file is self-contained: each line carries its own key so it can
        be imported onto another machine or merged back later. Returns the
        count of items written (0 when there is nothing to export).
        """
        path = Path(path)
        entries: list[str] = []
        for key in sorted(self.queues):
            for item in self.queues[key]:
                record = {"slot": key, "item": item.to_dict()}
                entries.append(json.dumps(record, ensure_ascii=False))
        if not entries:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return 0
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text("\n".join(entries) + "\n", encoding="utf-8")
        try:
            os.replace(tmp, path)
        except OSError:
            path.write_text("\n".join(entries) + "\n", encoding="utf-8")
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        return len(entries)

    def import_jsonl(self, path: str | os.PathLike) -> int:
        """Merge items from a JSONL file into this store.

        Every valid line whose (key, text) is not already present is added
        as a fresh pending prompt. Corrupt lines are skipped. Items with
        matching key+text are treated as duplicates and silently ignored.
        Returns the count of new items actually added.
        """
        path = Path(path)
        if not path.exists():
            return 0
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return 0
        existing = {
            (key, item.text)
            for key, items in self.queues.items()
            for item in items
        }
        added = 0
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            raw = row.get("item")
            if not isinstance(raw, dict):
                continue
            item = PromptItem.from_dict(raw)
            if item is None:
                continue
            key = str(row.get("slot", "0"))
            if (key, item.text) in existing:
                continue
            self.queues.setdefault(key, []).append(item)
            existing.add((key, item.text))
            added += 1
        return added
