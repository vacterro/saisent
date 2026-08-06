"""Per-agent quota state, cached, with a countdown the UI can read every second.

Two separate costs were being paid on the wrong thread. Scanning an agent's
transcripts means opening up to twenty files and reading their tails; doing
that inside a sidebar refresh froze the window every few seconds. And the
countdown -- the only part that actually changes between scans -- needs no disk
at all once a reset time is known.

So: `scan()` is blocking and belongs on a worker thread, `reading()` is a
cached value, and `label()` derives the remaining time from the cached reset
time at whatever rate the UI ticks.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

# A scan older than this is worth repeating. Quota text does not change second
# to second, and rescanning on every sidebar refresh is what caused the stalls.
DEFAULT_TTL_SECONDS = 60.0

# Once the reset time has passed, re-read rather than trusting arithmetic: the
# agent is the authority on whether it is actually free again.
RECHECK_AFTER_RESET_SECONDS = 5.0


def humanize(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}ч {minutes:02d}м"
    if minutes:
        return f"{minutes}м {secs:02d}с"
    return f"{secs}с"


@dataclass
class LimitReading:
    """What one agent's own text said about its quota, and when we read it."""

    agent: str
    reached: bool = False
    resets_at: datetime | None = None
    checked_at: float = 0.0
    error: str = ""

    def seconds_left(self, now: datetime | None = None) -> int | None:
        if self.resets_at is None:
            return None
        now = datetime.now() if now is None else now
        return max(0, int((self.resets_at - now).total_seconds()))

    def clear_by_now(self, now: datetime | None = None) -> bool:
        """True when the named reset time has already gone by."""
        left = self.seconds_left(now)
        return left is not None and left <= 0

    def label(self, now: datetime | None = None) -> str:
        if self.error:
            return f"нет данных ({self.error})"
        if not self.reached:
            return "свободен"
        left = self.seconds_left(now)
        if left is None:
            return "ЛИМИТ, время сброса не названо"
        if left <= 0:
            return "ЛИМИТ, сброс уже прошёл — проверяю"
        return f"до {self.resets_at.strftime('%H:%M')} ({humanize(left)})"

    def blocking(self, now: datetime | None = None) -> bool:
        """Whether a send should hold. A passed reset time no longer blocks."""
        if not self.reached:
            return False
        return not self.clear_by_now(now)


class LimitMonitor:
    """Reads quota state per agent, caches it, and answers instantly after."""

    def __init__(
        self,
        registry,
        scan_text,
        ttl: float = DEFAULT_TTL_SECONDS,
        clock=time.monotonic,
    ) -> None:
        self.registry = registry
        self.scan_text = scan_text
        self.ttl = float(ttl)
        self.clock = clock
        self._readings: dict[str, LimitReading] = {}

    def reading(self, agent: str) -> LimitReading | None:
        return self._readings.get(agent)

    def readings(self) -> dict[str, LimitReading]:
        return dict(self._readings)

    def stale(self, agent: str, now: datetime | None = None) -> bool:
        reading = self._readings.get(agent)
        if reading is None:
            return True
        if self.clock() - reading.checked_at >= self.ttl:
            return True
        # A reading whose reset time has arrived is stale whatever the TTL
        # says: that is the exact moment the answer is expected to change.
        return reading.reached and reading.clear_by_now(now)

    def scan_agent(self, agent: str, now: datetime | None = None) -> LimitReading:
        """Blocking: reads the agent's recent transcripts and parses them."""
        try:
            text = self.registry.recent_transcripts(agent)
        except Exception as exc:
            reading = LimitReading(
                agent=agent, checked_at=self.clock(), error=str(exc)[:60]
            )
            self._readings[agent] = reading
            return reading
        try:
            state = self.scan_text(text or "")
        except Exception as exc:
            reading = LimitReading(
                agent=agent, checked_at=self.clock(), error=str(exc)[:60]
            )
            self._readings[agent] = reading
            return reading
        reading = LimitReading(
            agent=agent,
            reached=bool(getattr(state, "reached", False)),
            resets_at=getattr(state, "resets_at", None),
            checked_at=self.clock(),
        )
        self._readings[agent] = reading
        return reading

    def set_reading(
        self,
        agent: str,
        reached: bool,
        resets_at: datetime | None = None,
        error: str = "",
    ) -> LimitReading:
        """Record a limit read from something better than prose.

        Claude Code writes a structured `429` record and no prose at all, so
        the text scanner can never see its limit. This is how that detector
        gets its answer in.
        """
        reading = LimitReading(
            agent=agent,
            reached=bool(reached),
            resets_at=resets_at,
            checked_at=self.clock(),
            error=error,
        )
        self._readings[agent] = reading
        return reading

    def apply_plan(
        self,
        agent: str,
        last_send: datetime | None = None,
        overrides: dict | None = None,
    ) -> LimitReading | None:
        """Fill in a reset time the agent never named, from its own rule.

        Freebuff and CodeNomad never state a time, and Claude's window is a
        rolling five hours rather than a wall clock, so without this a real
        limit shows «время сброса не названо» and blocks with no countdown.
        A time the agent DID state is left alone -- see `quota_plan`.
        """
        from SAISENT_sessions.quota_plan import predicted_reset

        reading = self._readings.get(agent)
        if reading is None or not reading.reached or reading.resets_at is not None:
            return reading
        when, _source = predicted_reset(
            agent, datetime.now(), last_send=last_send, overrides=overrides
        )
        if when is None:
            return reading
        patched = LimitReading(
            agent=reading.agent,
            reached=True,
            resets_at=when,
            checked_at=reading.checked_at,
            error=reading.error,
        )
        self._readings[agent] = patched
        return patched

    def scan(self, agents, force: bool = False, now: datetime | None = None) -> dict:
        """Scan every agent whose cached reading has gone stale."""
        for agent in agents:
            if force or self.stale(agent, now):
                self.scan_agent(agent, now)
        return self.readings()

    def blocking_agents(self, now: datetime | None = None) -> list[str]:
        return [
            agent
            for agent, reading in self._readings.items()
            if reading.blocking(now)
        ]

    def summary(self, now: datetime | None = None) -> str:
        """One line for the status bar: the worst state across all agents."""
        if not self._readings:
            return "лимиты не проверялись"
        blocked = [r for r in self._readings.values() if r.blocking(now)]
        if not blocked:
            return "лимиты: все агенты свободны"
        soonest = min(
            blocked,
            key=lambda r: (r.seconds_left(now) is None, r.seconds_left(now) or 0),
        )
        return f"{soonest.agent}: {soonest.label(now)}"
