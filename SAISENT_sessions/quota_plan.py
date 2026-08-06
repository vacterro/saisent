"""When each agent's quota comes back, when the agent will not say so itself.

`limits.scan_text` reads a reset time out of the agent's own words, which is
the best source when it exists. It often does not: Freebuff never names a
time, CodeNomad never names a time, and Claude's window is a rolling five
hours that starts at the first message of the window rather than at midnight.

So each agent gets a rule:

* `daily HH:MM`  -- a wall-clock reset, same time every day (Freebuff 10:00,
  CodeNomad 03:00).
* `rolling Nh`   -- N hours counted from the last prompt that went out, which
  is what a shift-style window actually is.
* `text`         -- no rule; whatever the transcript says, or nothing.

A rule never overrides a time the agent stated. The agent is the authority on
its own quota; these fill the silence, they do not argue with it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

DAILY = "daily"
ROLLING = "rolling"
TEXT = "text"

# What the user actually observes on this machine.
DEFAULT_PLANS = {
    "freebuff": f"{DAILY} 10:00",
    "codenomad": f"{DAILY} 03:00",
    "claude-code": f"{ROLLING} 5h",
    "antigravity": TEXT,
}

_DAILY_RE = re.compile(r"^daily\s+(\d{1,2}):(\d{2})$", re.I)
_ROLLING_RE = re.compile(r"^rolling\s+(\d+(?:\.\d+)?)\s*h$", re.I)


@dataclass(frozen=True)
class Plan:
    kind: str
    hour: int = 0
    minute: int = 0
    hours: float = 0.0

    def describe(self) -> str:
        if self.kind == DAILY:
            return f"каждый день в {self.hour:02d}:{self.minute:02d}"
        if self.kind == ROLLING:
            hours = int(self.hours) if float(self.hours).is_integer() else self.hours
            return f"через {hours}ч после отправки"
        return "по словам агента"

    def next_reset(
        self, now: datetime, last_send: datetime | None = None
    ) -> datetime | None:
        """When the quota is next expected back, or None for `text` plans."""
        if self.kind == DAILY:
            target = now.replace(
                hour=self.hour, minute=self.minute, second=0, microsecond=0
            )
            if target <= now:
                target += timedelta(days=1)
            return target
        if self.kind == ROLLING:
            # Counted from the last prompt, because that is what starts the
            # window. With nothing sent yet there is no window to count from.
            if last_send is None:
                return None
            return last_send + timedelta(hours=self.hours)
        return None


def parse(spec: str) -> Plan:
    """`daily 10:00` / `rolling 5h` / anything else -> a `text` plan."""
    spec = (spec or "").strip()
    match = _DAILY_RE.match(spec)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return Plan(DAILY, hour=hour, minute=minute)
        return Plan(TEXT)
    match = _ROLLING_RE.match(spec)
    if match:
        hours = float(match.group(1))
        return Plan(ROLLING, hours=hours) if hours > 0 else Plan(TEXT)
    return Plan(TEXT)


def plan_for(agent: str, overrides: dict | None = None) -> Plan:
    table = dict(DEFAULT_PLANS)
    table.update(overrides or {})
    return parse(table.get(agent, TEXT))


def predicted_reset(
    agent: str,
    now: datetime,
    last_send: datetime | None = None,
    stated: datetime | None = None,
    overrides: dict | None = None,
) -> tuple[datetime | None, str]:
    """`(when, source)` -- the agent's own word beats any rule we invented."""
    if stated is not None:
        return stated, "агент назвал"
    plan = plan_for(agent, overrides)
    when = plan.next_reset(now, last_send)
    if when is None:
        return None, plan.describe()
    return when, plan.describe()
