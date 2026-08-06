"""What to do with the machine once the queue has gone out.

The point of a scheduled run is that nobody is watching it, so the screen has
no reason to stay lit until morning. Turning the monitor off is the safe
member of this family: the session stays unlocked and interactive, so a later
scheduled batch can still type.

Locking and sleeping are not safe in the same way, and the difference is not
cosmetic:

* **Lock** switches the input desktop away from `Default`. Every later
  keystroke send is swallowed -- which is precisely the failure the
  locked-desktop guard exists to catch. Only a CDP send survives it.
* **Sleep** stops the clock entirely. A batch scheduled for 05:00 does not
  happen; the machine wakes up with the queue exactly where it was.

So each action carries its own warning, and the UI shows it before the run,
not after.
"""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from typing import Callable

NOTHING = "nothing"
MONITOR_OFF = "monitor_off"
LOCK = "lock"
SLEEP = "sleep"


@dataclass(frozen=True)
class AfterAction:
    key: str
    label: str
    warning: str = ""


ACTIONS = (
    AfterAction(NOTHING, "ничего"),
    AfterAction(MONITOR_OFF, "погасить экран"),
    AfterAction(
        LOCK,
        "заблокировать",
        "после блокировки клавиатурная отправка перестанет работать — "
        "останется только через отладчик",
    ),
    AfterAction(
        SLEEP,
        "сон",
        "во сне расписание не сработает вообще — очередь дождётся пробуждения",
    ),
)

BY_KEY = {action.key: action for action in ACTIONS}
BY_LABEL = {action.label: action for action in ACTIONS}


def label_for(key: str) -> str:
    action = BY_KEY.get(key)
    return action.label if action else BY_KEY[NOTHING].label


def key_for(label: str) -> str:
    action = BY_LABEL.get((label or "").strip())
    return action.key if action else NOTHING


def warning_for(key: str) -> str:
    action = BY_KEY.get(key)
    return action.warning if action else ""


def monitor_off() -> None:
    """Ask every top-level window to power the display down."""
    user32 = ctypes.windll.user32
    HWND_BROADCAST = 0xFFFF
    WM_SYSCOMMAND = 0x0112
    SC_MONITORPOWER = 0xF170
    MONITOR_POWER_OFF = 2
    user32.PostMessageW(
        HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, MONITOR_POWER_OFF
    )


def lock_workstation() -> None:
    ctypes.windll.user32.LockWorkStation()


def sleep_machine() -> None:
    # SetSuspendState(Hibernate=False, Force=False, WakeupEventsDisabled=False)
    ctypes.windll.powrprof.SetSuspendState(False, False, False)


HANDLERS: dict[str, Callable[[], None]] = {
    MONITOR_OFF: monitor_off,
    LOCK: lock_workstation,
    SLEEP: sleep_machine,
}


def run_after(key: str, handlers: dict | None = None) -> tuple[bool, str]:
    """Perform the post-run action. `(ran, message)`.

    Never raises: a machine action failing must not turn a successful delivery
    into an error the user reads as "nothing was sent".
    """
    key = (key or NOTHING).strip()
    if key == NOTHING:
        return False, ""
    handler = (handlers or HANDLERS).get(key)
    if handler is None:
        return False, f"неизвестное действие после отправки: {key!r}"
    if os.name != "nt":  # pragma: no cover - Windows-only path
        return False, "действия после отправки только для Windows"
    try:
        handler()
    except Exception as exc:
        return False, f"{label_for(key)}: не вышло ({exc})"
    return True, f"после отправки: {label_for(key)}"
