"""Live agent-session discovery and per-session prompt queues for SAISENT.

The GUI used to ask the user to describe the target by hand: an agent name in
a combobox, a glob for an idle probe, a title fragment. Every one of those is
a restatement of something the agent already wrote to disk. This package reads
it instead.

Two halves:

- `discover` — who is running right now (name, project, PID, idle/busy).
- `queues`   — what is waiting to be typed into each of them, in order.

Both are pure enough to test without a window on screen: every provider takes
its roots and its clock as arguments.
"""

from .discover import (
    Session,
    SessionRegistry,
    ClaudeCodeProvider,
    FreebuffProvider,
    AntigravityProvider,
    CodeNomadProvider,
    default_registry,
    pid_alive,
    process_running,
)
from .queues import PromptItem, QueueStore

__all__ = [
    "Session",
    "SessionRegistry",
    "ClaudeCodeProvider",
    "FreebuffProvider",
    "AntigravityProvider",
    "CodeNomadProvider",
    "default_registry",
    "pid_alive",
    "process_running",
    "PromptItem",
    "QueueStore",
]
