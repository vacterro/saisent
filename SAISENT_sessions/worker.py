"""The send worker: one batch of prompts, on a daemon thread.

Lifted out of the GUI file so the schedule gate, the quota gate and the
per-item bookkeeping can be tested without a window on screen -- and so the Tk
shell stays a shell. Everything it touches (window activation, key presses,
the clipboard) blocks for hundreds of milliseconds, which is exactly why none
of it may run on the Tk thread.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

from SAISENT_sessions.deliver import Deliverer
from SAISENT_sessions.discover import SessionRegistry
from SAISENT_sessions.queues import (
    STATE_FAILED,
    STATE_PENDING,
    STATE_SENDING,
    STATE_SENT,
)


# ------------------------------------------------------------- send worker
class SendWorker:
    """Runs a delivery plan on a daemon thread and reports through a queue.

    Everything it touches -- window activation, key presses, the clipboard --
    blocks for hundreds of milliseconds at a time. None of that may happen on
    the Tk thread, which is the whole reason the old console felt like glue.
    """

    def __init__(self, deliverer: Deliverer, report, registry: SessionRegistry = None) -> None:
        self.deliverer = deliverer
        self.report = report
        self.registry = registry
        self.limit_monitor = None
        # "waiting" while parked on a schedule, "sending" once prompts move.
        # The UI uses it to keep the queue editable during the wait.
        self.phase = ""
        # How long to let a busy agent finish before moving to the next prompt.
        self.busy_wait_seconds = 300.0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def resolve_session(self, session):
        """Who owns this session key right now, or None if it is gone.

        Without a registry there is nothing to re-check against, so the job's
        own snapshot stands -- that is what tests use.
        """
        if self.registry is None:
            return session
        try:
            for fresh in self.registry.discover():
                if fresh.key == session.key:
                    return fresh
        except Exception:
            # A failed lookup is not proof the session died; better to send to
            # the snapshot than to silently drop a prompt.
            return session
        return None

    def _emit(self, kind: str, *args) -> None:
        """Report one event as a single `(kind, args)` value.

        The callback is whatever the caller already has -- `Queue.put`, a
        `list.append` in a test -- and both take exactly one argument. Passing
        `kind` and the payload as separate positionals is what silently broke
        every test double that used `append`.
        """
        self.report((kind, args))

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self, jobs, gap_ms: int, dry: bool, schedule_time: str = "", check_limits: bool = False, schedules: dict | None = None) -> bool:
        if self.running:
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(list(jobs), int(gap_ms), bool(dry), schedule_time, check_limits, schedules),
            name="SAISENT-Send",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def _wait_for_quota(self, agent: str, sent: int) -> bool:
        """Hold until the agent's quota frees up. False means the run stopped.

        Ticks once a second so the countdown in the status bar actually moves;
        the disk is only touched when the cached reading goes stale, which the
        monitor decides -- including the moment a named reset time arrives.
        """
        monitor = getattr(self, "limit_monitor", None)
        if monitor is None:
            return True
        announced = False
        while True:
            if self._stop.is_set():
                self._emit("done", sent, "остановлено")
                return False
            wall = datetime.now()
            try:
                monitor.scan([agent], now=wall)
            except Exception as exc:
                self._emit("log", f"Проверка лимита {agent} сорвалась: {exc}")
                return True
            reading = monitor.reading(agent)
            if reading is None or not reading.blocking(wall):
                if announced:
                    self._emit("log", f"{agent}: лимит снят, продолжаю.")
                return True
            announced = True
            self._emit(
                "status", "RUNNING", f"Жду сброса лимита — {reading.label(wall)}"
            )
            self._stop.wait(1.0)

    def _run(self, jobs, gap_ms: int, dry: bool, schedule_time: str, check_limits: bool, schedules: dict | None = None, now: datetime | None = None) -> None:
        # Per-session override wins over the global time. A session with its
        # own HH:MM fires at its own hour; everyone else inherits the global.
        segments: dict[str, list] = {}
        for session, item, tab_index in jobs:
            own = (schedules or {}).get(session.key, "")
            key = own or schedule_time
            segments.setdefault(key, []).append((session, item, tab_index))

        sent = 0
        unconfirmed = 0
        failed = 0
        skipped = 0
        # Immediate first, then the scheduled ones in the order they actually
        # occur. Sorting the empty key last parked every "send now" job behind
        # a session that happened to carry an override, and sorting the rest
        # as strings put tomorrow 03:00 ahead of tonight 23:00. `now` is
        # injectable so tests can pin the clock instead of depending on the
        # wall clock (which flips "tonight vs tomorrow" after midnight).
        now = datetime.now() if now is None else now

        def when(seg_time: str):
            if not seg_time:
                return (0, now)
            target = self.next_occurrence(seg_time, now)
            return (1, target) if target else (2, now)

        for seg_time in sorted(segments, key=when):
            seg_jobs = segments[seg_time]
            if seg_time and self.next_occurrence(seg_time, now) is None:
                # An unreadable override must never become "send immediately".
                for session, item, _tab in seg_jobs:
                    reason = f"нечитаемое время {seg_time!r} — не отправлено"
                    item.state = STATE_FAILED
                    item.reason = reason
                    self._emit(
                        "item_state", session.key, item.id, STATE_FAILED, reason, False
                    )
                failed += len(seg_jobs)
                continue
            self.phase = "waiting" if seg_time else "sending"
            if seg_time:
                if not self._wait_for_time(seg_time):
                    self._emit("done", sent, "остановлено")
                    return
            self.phase = "sending"
            result = self._send_segment(seg_jobs, gap_ms, dry, check_limits, sent)
            if result is None:
                return  # stopped mid-segment; done already emitted
            s, u, f, sk = result
            sent += s
            unconfirmed += u
            failed += f
            skipped += sk
        tail = []
        if failed:
            tail.append(f"{failed} с ошибкой")
        if skipped:
            tail.append(f"{skipped} пропущено (сессии нет)")
        if unconfirmed:
            tail.append(f"{unconfirmed} не подтверждено")
        if tail:
            self._emit("done", sent, "готово, " + ", ".join(tail) + " — в очереди")
        else:
            self._emit("done", sent, "готово")

    @staticmethod
    def next_occurrence(schedule_time: str, now: datetime | None = None):
        """`HH:MM` as the next datetime it happens, or None if unreadable.

        Returning None rather than "now" matters: the old code swallowed a
        parse error and fell through to sending immediately, so one typo in an
        override turned a 03:00 batch into an instant one.
        """
        now = datetime.now() if now is None else now
        try:
            hour, minute = (int(part) for part in str(schedule_time).split(":", 1))
        except (TypeError, ValueError):
            return None
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target

    def _wait_for_time(self, schedule_time: str) -> bool:
        """Wait until the next `HH:MM`. False means the run stopped."""
        target = self.next_occurrence(schedule_time)
        if target is None:
            return False
        while datetime.now() < target:
            if self._stop.is_set():
                return False
            diff = int((target - datetime.now()).total_seconds())
            self._emit(
                "status",
                "RUNNING",
                f"Ждём расписания {schedule_time} "
                f"(осталось {diff // 60}м {diff % 60}с)",
            )
            self._stop.wait(1.0)
        return True

    def _send_segment(self, jobs, gap_ms: int, dry: bool, check_limits: bool, base_sent: int):
        """Send one time-segment of jobs. Returns (sent_delta, unconfirmed,
        failed, skipped), or None when the run stopped (done emitted)."""
        sent = base_sent
        unconfirmed = 0
        failed = 0
        skipped = 0
        try:
            for index, (session, item, tab_index) in enumerate(jobs):
                if self._stop.is_set():
                    self._emit("done", sent, "остановлено")
                    return None

                # The batch may have been queued hours ago. Ask who owns this
                # key NOW: a session that died overnight would otherwise still
                # resolve its agent's window and paste into whatever is there.
                session = self.resolve_session(session)
                if session is None:
                    skipped += 1
                    original = jobs[index][0]
                    reason = "сессия закрылась, пока промпт ждал"
                    item.state = STATE_FAILED
                    item.reason = reason
                    self._emit(
                        "item_state", original.key, item.id, STATE_FAILED, reason, False
                    )
                    self._emit("log", f"{original.name}: пропущен — {reason}")
                    continue
                tab_index = session.tab_hint if tab_index is not None else None

                if check_limits and not self._wait_for_quota(session.agent, sent):
                    self._emit("done", sent, "остановлено")
                    return None

                if not dry:
                    # A dry run must leave the row exactly as it found it;
                    # marking it «шлётся» and then never clearing it left the
                    # queue showing a send that never happened.
                    self._emit(
                        "item_state", session.key, item.id, STATE_SENDING, "", False
                    )
                self._emit(
                    "status",
                    "RUNNING",
                    f"{index + 1}/{len(jobs)} -> {session.name}: {item.label[:40]}",
                )
                result = self.deliverer.deliver(session, item.text, tab_index, dry=dry)
                if dry:
                    # Пробный прогон ничего не отправлял — состояние не трогаем.
                    self._emit("log", f"{session.name}: {result}")
                    continue
                if result.ok and result.confirmed:
                    state_val = STATE_SENT
                    reason = result.reason
                elif result.ok:
                    # Клавиши ушли, но стор сессии не двинулся: агент в квоте,
                    # занят или промпт реально не дошёл. Помечать «ушло» было
                    # бы враньём — промпт остаётся в очереди, считаем его
                    # неподтверждённым, а не отправленным.
                    state_val = STATE_PENDING
                    reason = "не подтверждено — агент не показал активности"
                else:
                    state_val = STATE_FAILED
                    reason = result.reason
                confirmed = result.ok and result.confirmed
                # Write the outcome onto the item the caller handed us, not
                # only into a report. The queue pane reads these objects, and
                # a state that exists solely as a message in flight is a state
                # nobody can see if the UI thread is busy.
                item.state = state_val
                item.reason = reason
                item.confirmed = confirmed
                if state_val == STATE_SENT:
                    item.sent_at = datetime.now().isoformat(timespec="seconds")
                self._emit("item_state", session.key, item.id, state_val,
                            reason, confirmed)
                self._emit("log", f"{session.name}: {result}")
                if confirmed:
                    sent += 1
                elif result.ok:
                    unconfirmed += 1
                else:
                    # Skip, do not stop. Overnight, one bad target used to mean
                    # every prompt behind it never went at all -- the failure
                    # is reported and counted, and the rest of the batch runs.
                    failed += 1
                if index + 1 < len(jobs):
                    if gap_ms > 0:
                        wait_until = time.time() + gap_ms / 1000.0
                        while time.time() < wait_until:
                            if self._stop.is_set():
                                self._emit("done", sent, "остановлено")
                                return None
                            rem = max(0, wait_until - time.time())
                            self._emit("status", "RUNNING", f"Ждём {rem:.1f}с перед следующим...")
                            self._stop.wait(min(0.2, rem))

                    if self.registry and result.ok and result.confirmed:
                        from SAISENT_sessions.discover import STATE_IDLE

                        # Bounded on purpose. An agent that stays busy -- a long
                        # turn, a stuck tool call -- used to park this loop
                        # forever, and the rest of the queue never went out.
                        deadline = time.time() + self.busy_wait_seconds
                        while time.time() < deadline:
                            if self._stop.is_set():
                                self._emit("done", sent, "остановлено")
                                return None
                            sessions = self.registry.discover()
                            current = next(
                                (s for s in sessions if s.key == session.key), None
                            )
                            if not current or current.state == STATE_IDLE:
                                break
                            left = int(deadline - time.time())
                            self._emit(
                                "status",
                                "RUNNING",
                                f"Ждём ответа {session.name}... ({left}с)",
                            )
                            self._stop.wait(1.0)
        except Exception as exc:  # pragma: no cover - defensive
            self._emit("log", f"Сбой отправки: {exc}")
            self._emit("done", sent, f"сбой: {exc}")
            return None
        return (sent - base_sent, unconfirmed, failed, skipped)
