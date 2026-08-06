"""SAISENT Watcher — queue prompts and feed them to an agent as it goes idle.

Copied from FastPrompter's core/watcher and made self-contained: the queue,
the idle probes and the engine state machine are the parts worth testing
without a GUI, so they stay free of tkinter and run anywhere CPython runs.

Modules:

* `engine`   — the state machine: when may the next prompt go out?
* `queue`    — per-target prompt queues (one strict order each)
* `probes`   — cheap signals that say "the agent has stopped working"
* `sender`   — the only part that can do damage; every strategy is injected
* `win32`    — reading and driving windows through ctypes, no dependencies
* `cdp`      — driving a Chromium app through its DevTools socket
* `adapter`  — one agent described in config, not in code
* `skills`   — the token prepended to a queued prompt
* `limits`   — reading "limit reached" out of the agent's own words
* `limit_scan` — asking every configured agent whether it is limited now
"""
