"""Put one queued prompt inside one running session.

Three problems this solves that the old macro runner did not:

1. **Addressing.** A macro sent keystrokes to whatever had focus. Here the
   window is resolved per agent, activated, and the session's tab is selected
   before a single character moves.
2. **Speed.** Typing a pasted paragraph one `SendInput` at a time takes
   `len(text) * key_delay` milliseconds and drops characters when the target
   stalls. The clipboard delivers it atomically.
3. **Proof.** `WM_GETTEXT` returns nothing for a Chromium window, so the old
   read-back could never confirm anything against these agents -- it just
   reported "unconfirmed" forever. The agent's own on-disk activity is the
   confirmation instead: the same file whose timestamp drives the idle sensor
   has to move after a prompt lands.
"""

from __future__ import annotations

import ctypes
import os
import socket
import subprocess
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Callable


def tcp_port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    """Whether anything is listening. The port FILE outlives the flag.

    Both agents leave a stale `DevToolsActivePort` behind from an earlier run,
    so its existence proves nothing; only a connect does.
    """
    try:
        with socket.create_connection((host, int(port)), timeout):
            return True
    except OSError:
        return False

# Which window belongs to which agent. Titles are matched as substrings; every
# `claude.exe` window is literally called "Claude", which is exactly why the
# session name has to come from disk instead.
DEFAULT_WINDOW_TARGETS = {
    "claude-code": ("claude.exe", "Chrome_WidgetWin_1", "Claude"),
    "freebuff": ("Freebuff.exe", "Chrome_WidgetWin_1", "Freebuff"),
    "antigravity": ("Antigravity.exe", "Chrome_WidgetWin_1", "Antigravity"),
    "codenomad": ("CodeNomad.exe", "Chrome_WidgetWin_1", "CodeNomad"),
}

# Tab shortcuts are Ctrl+1..Ctrl+9 in every one of these Electron apps; there
# is no Ctrl+10, so a tenth session cannot be addressed this way.
MAX_TAB_INDEX = 9

# Agents that open one window per workspace, whose title therefore carries the
# project name and can be used as an address.
#
# Antigravity is NOT one of them, however much its file layout suggests it.
# Measured on 2026-08-05: its only visible window is titled exactly
# "Antigravity" -- no file, no folder, no separator. Matching the project name
# against that title can never succeed, which is precisely the failure in
#   window not found: exe='Antigravity.exe', title contains='_FastPrompter'
# So the set is empty until an agent actually earns a place in it. Leaving a
# hopeful entry here is worse than having none: it turns "cannot address this"
# into "addressed it, and missed".
WINDOW_PER_PROJECT: set[str] = set()

# How to ask a VS Code-family editor to focus a workspace it already has open.
# `--reuse-window` is the documented flag; passing a bare path can open a
# second window, which is how a prompt ends up typed into an empty editor.
EDITOR_EXECUTABLES = {
    "antigravity": (
        r"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe",
        "--reuse-window",
    ),
}

# Where each Electron app writes its DevTools port, when it was started with
# `--remote-debugging-port`. A live port is the only transport that can pick a
# conversation by name and read the field back; everything else is keystrokes
# aimed at whatever the app happens to be showing.
CDP_PORT_FILES = {
    "antigravity": r"%APPDATA%\Antigravity\DevToolsActivePort",
    "claude-code": r"%APPDATA%\Claude\DevToolsActivePort",
    # CodeNomad ships as an Electron app whose userData folder is still named
    # after the shell it was forked from. Measured, not guessed: the file holds
    # the port CodeNomad.exe is actually listening on.
    "codenomad": r"%APPDATA%\Plasticity\DevToolsActivePort",
}

# What to type into, and what to click first, inside each agent's page.
# Read off the live DOM on 2026-08-05; every value below was verified to match
# the exact set of names the matching provider reports.
#
#   antigravity  button[class*="headerbtn"]  -> 16 buttons, one per project,
#                                               labels SAISENT, _SAIPEN, ...
#   codenomad    span.session-item-title     -> one per session, label is the
#                                               session title; the click
#                                               bubbles to .session-item-base
#
# `dialog_selector` empty means "no way to pick a conversation": the text goes
# to whichever one the app is showing.
#
# Selectors are comma-separated fallback chains on purpose. `querySelectorAll`
# accepts a selector list, so an app redesign that renames one hook does not
# take delivery down with it -- verified against both spellings of the
# Antigravity project button.
CDP_PROFILES = {
    "antigravity": {
        "agent": "antigravity",
        "selector": '[aria-label="Message input"]',
        "dialog_selector": (
            'button[data-project-card="true"], button[class*="headerbtn"]'
        ),
        "dialog_attr": "",
        # Those buttons are PROJECTS, not conversations. Two conversations in
        # one workspace are one addressable target, which is why the provider
        # collapses them instead of listing the same name three times.
        "dialog_from": "project",
        "submit": "enter",
    },
    "codenomad": {
        "agent": "codenomad",
        "selector": "textarea.prompt-input",
        "dialog_selector": "span.session-item-title, .session-list-item",
        "dialog_attr": "",
        "dialog_from": "name",
        "submit": "enter",
    },
}

# Reads the labels of every switchable conversation currently on the page.
_DIALOG_LABELS_JS = """
(() => {
  const items = [...document.querySelectorAll(SELECTOR)]
    .filter(e => e.offsetWidth || e.offsetHeight);
  return JSON.stringify(items.map(
    e => (e.textContent || '').replace(/\\s+/g, ' ').trim()).filter(Boolean));
})()
"""


def _json_string(value: str) -> str:
    import json

    return json.dumps(value)


# Failures worth a second go: the window was busy, minimised, or something
# stole focus for a moment. Everything else -- a refusal, a bad tab index, a
# CDP sender reporting the field is occupied -- means trying again changes
# nothing, so the batch stops and says why.
TRANSIENT_MARKERS = (
    "window not found",
    "could not activate",
    "lost focus",
    "focus moved away",
    "clipboard",
)


def _is_transient(reason: str) -> bool:
    lowered = (reason or "").lower()
    return any(marker in lowered for marker in TRANSIENT_MARKERS)


def desktop_is_interactive() -> bool:
    """Whether synthesized input can reach anything at all right now.

    A locked workstation (or an active screensaver, or the login screen)
    switches the input desktop away from `Default`. `SendInput` still returns
    success there and every keystroke goes nowhere -- which is exactly the
    overnight failure: the batch reports OK and the morning shows an empty
    chat. `OpenInputDesktop` fails on a desktop we do not own, and that is the
    cheapest honest answer.

    Only keystroke delivery cares. A CDP send talks to a socket and works fine
    with the screen locked, which is the strongest argument for the debugger.
    """
    if os.name != "nt":  # pragma: no cover - Windows-only path
        return True
    user32 = ctypes.windll.user32
    DESKTOP_SWITCHDESKTOP = 0x0100
    handle = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
    if not handle:
        return False
    try:
        name = ctypes.create_unicode_buffer(256)
        needed = ctypes.c_ulong()
        # UOI_NAME == 2. "Default" is the interactive desktop; "Winlogon" and
        # "Screen-saver" are not.
        if user32.GetUserObjectInformationW(
            handle, 2, name, ctypes.sizeof(name), ctypes.byref(needed)
        ):
            return name.value.lower() == "default"
        return True
    finally:
        user32.CloseDesktop(handle)

# The command that makes the reliable transport available. Shown to the user;
# never run automatically -- restarting an agent kills whatever it was doing.
CDP_RELAUNCH_HINT = {
    "antigravity": (
        r'"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe" '
        "--remote-debugging-port=28194"
    ),
    # Measured path is versioned (`app-1.25927.0`), so it changes on every
    # update; the folder is stable, the executable inside it is not.
    "claude-code": (
        r'"%LOCALAPPDATA%\AnthropicClaude\app-<version>\claude.exe" '
        "--remote-debugging-port=9222"
    ),
    "codenomad": (
        r'"<CodeNomad>\CodeNomad.exe" --remote-debugging-port=9223'
    ),
}


@dataclass
class DeliveryResult:
    ok: bool
    reason: str
    confirmed: bool = False
    plan: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        mark = "OK" if self.ok else "FAIL"
        seal = "confirmed" if self.confirmed else "unconfirmed"
        return f"{mark} ({seal}): {self.reason}"


class Win32Clipboard:
    """Set CF_UNICODETEXT, the way every paste target expects to find it.

    Tk's own clipboard is not usable here: Tk holds the selection itself, so
    the text dies with the app and some targets never see it at all.
    """

    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002

    def __init__(self, retries: int = 8, sleep: Callable[[float], None] = time.sleep):
        self.retries = int(retries)
        self.sleep = sleep

    def set(self, text: str) -> bool:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p

        # Another process can hold the clipboard open for a few milliseconds.
        # Retrying is the documented answer; failing on the first miss is how
        # a paste silently sends the previous prompt twice.
        for attempt in range(self.retries):
            if user32.OpenClipboard(None):
                break
            self.sleep(0.05 * (attempt + 1))
        else:
            return False

        try:
            user32.EmptyClipboard()
            data = ctypes.create_unicode_buffer(text)
            size = ctypes.sizeof(data)
            handle = kernel32.GlobalAlloc(self.GMEM_MOVEABLE, size)
            if not handle:
                return False
            locked = kernel32.GlobalLock(handle)
            if not locked:
                kernel32.GlobalFree(handle)
                return False
            ctypes.memmove(locked, ctypes.byref(data), size)
            kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(self.CF_UNICODETEXT, handle):
                kernel32.GlobalFree(handle)
                return False
            # Ownership passed to the clipboard: freeing it here would hand the
            # paste target a dangling block.
            return True
        finally:
            user32.CloseClipboard()

    def get(self) -> str | None:
        """Read the current CF_UNICODETEXT, or None when there is no text.

        The restore half of the clipboard guard (T-052): a send must not
        destroy what the user copied, so the deliverer snapshots the clipboard
        before the paste and puts it back after. Nothing on the clipboard that
        is not text is touched -- only CF_UNICODETEXT is ever read or set.
        """
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalSize.restype = ctypes.c_size_t
        kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
        if not user32.OpenClipboard(None):
            return None
        try:
            handle = user32.GetClipboardData(self.CF_UNICODETEXT)
            if not handle:
                return None
            locked = kernel32.GlobalLock(handle)
            if not locked:
                return None
            try:
                size = kernel32.GlobalSize(locked)
                if size < 2:
                    return ""
                raw = ctypes.string_at(locked, size)
                return raw.decode("utf-16-le", errors="replace").rstrip("\x00")
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()


class Deliverer:
    """Types one prompt into one session, and says whether it landed."""

    def __init__(
        self,
        api,
        clipboard=None,
        activity: Callable[[str], float] | None = None,
        targets: dict | None = None,
        activation_timeout_ms: int = 10000,
        key_delay_ms: int = 45,
        settle_ms: int = 400,
        submit: str = "ENTER",
        confirm_timeout: float = 10.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        cdp_sender=None,
        cdp_sender_factory: Callable[[dict], object] | None = None,
        cdp_probe: Callable[[int], bool] | None = None,
        cdp_titles: dict | None = None,
        activity_map=None,
        dialog_probe_timeout: float = 6.0,
        attempts: int = 3,
        retry_delay_ms: int = 700,
        desktop_check: Callable[[], bool] = desktop_is_interactive,
    ) -> None:
        self.api = api
        self.clipboard = clipboard if clipboard is not None else Win32Clipboard()
        self.activity = activity
        self.targets = dict(targets or DEFAULT_WINDOW_TARGETS)
        self.activation_timeout_ms = int(activation_timeout_ms)
        self.key_delay_ms = int(key_delay_ms)
        self.settle_ms = int(settle_ms)
        self.submit = submit
        self.confirm_timeout = float(confirm_timeout)
        self.sleep = sleep
        self.clock = clock
        self.cdp_sender = cdp_sender
        self.cdp_sender_factory = cdp_sender_factory
        self._senders: dict = {}
        # Defaults to a real connect. Trusting the port file alone reports a
        # live debugger for an agent that was restarted without the flag --
        # the file survives, the listener does not.
        self.cdp_probe = tcp_port_open if cdp_probe is None else cdp_probe
        self.cdp_titles = dict(cdp_titles or {})
        # Optional: key -> last-activity for every session of every agent.
        # Lets a blind send name the chat the text actually reached.
        self.activity_map = activity_map
        self.dialog_probe_timeout = float(dialog_probe_timeout)
        self.attempts = int(attempts)
        self.retry_delay_ms = int(retry_delay_ms)
        self.desktop_check = desktop_check

    # ---- the reliable transport ---------------------------------------
    def cdp_status(self, agent: str) -> tuple[int, str]:
        """`(port, reason)` -- a live debugger port, or why there is none.

        This is the difference between addressing a conversation and hoping.
        Over CDP the page is picked by name, the field is read before and
        after the insert, and a half-written message blocks the send. Over
        keystrokes none of that is knowable.
        """
        port = 0
        path = CDP_PORT_FILES.get(agent)
        if path:
            expanded = os.path.expandvars(path)
            if os.path.exists(expanded):
                try:
                    from SAISENT_watcher.cdp import port_from_file

                    port = int(port_from_file(expanded) or 0)
                except Exception:
                    port = 0
        if not port:
            # The port file is the fragile half of this: it goes stale, and
            # some agents write it into a folder named after a different app.
            # A launch we configured uses a fixed port, so try that too --
            # the connect below is what actually decides either way.
            from SAISENT_sessions.launcher import DEFAULT_PORTS

            port = int(DEFAULT_PORTS.get(agent) or 0)
        if not port:
            return 0, "для этого агента порт не описан"
        if self.cdp_probe is not None and not self.cdp_probe(port):
            return 0, f"порт {port} записан, но не отвечает"
        return port, ""

    def sender_for(self, agent: str):
        """The CDP sender configured for this agent's page, or None.

        One sender per agent, because the field and the conversation list are
        different elements in every app. A single shared selector was fine
        while only one agent had a debugger; it silently types into nothing as
        soon as a second one appears.
        """
        if self.cdp_sender_factory is None:
            return self.cdp_sender
        cached = self._senders.get(agent)
        if cached is None:
            profile = CDP_PROFILES.get(agent)
            if profile is None:
                return None
            cached = self.cdp_sender_factory(profile)
            self._senders[agent] = cached
        return cached

    def dialog_label(self, session) -> str:
        """The text the agent's own list shows for this session.

        Antigravity's list is a row of PROJECT buttons, so the label is the
        project; CodeNomad lists session titles, so it is the name. Get this
        wrong and the click lands on nothing.
        """
        profile = CDP_PROFILES.get(session.agent) or {}
        if profile.get("dialog_from") == "project":
            return session.project_name or session.name
        return session.name

    def _cdp_target(self, session):
        """A live debuggable page for this session, or `(None, reason)`."""
        port, reason = self.cdp_status(session.agent)
        if not port:
            return None, reason
        try:
            from SAISENT_watcher.cdp import CdpTarget

            target = CdpTarget.from_port(
                port, title_match=self.cdp_titles.get(session.agent, "")
            )
        except Exception as exc:
            return None, f"cdp: {exc}"
        if target is None:
            return None, f"cdp: страница не найдена на порту {port}"
        # `from_port` takes no `dialog` argument -- passing one raised
        # TypeError, the fallback built a target with `dialog=""`, and
        # `CdpSender` then skipped conversation selection entirely. That is
        # why Antigravity was "just activating and pressing Enter": the click
        # that picks the chat never happened. Set it on the instance instead.
        target.dialog = self.dialog_label(session)
        return target, ""

    def dialog_labels(self, agent: str):
        """Every conversation the agent's page can currently switch to.

        `(labels, reason)`. `None` means "cannot tell" -- no debugger, no
        profile -- and callers must not treat that as "nothing is reachable".
        An empty set means the page rendered no switchable conversation at
        all, which is a real answer: CodeNomad only renders the open
        project's sessions, so the rest are genuinely unreachable.
        """
        profile = CDP_PROFILES.get(agent)
        if not profile or not profile.get("dialog_selector"):
            return None, "у агента нет списка диалогов в DOM"
        port, reason = self.cdp_status(agent)
        if not port:
            return None, reason
        try:
            from SAISENT_watcher.cdp import CdpTarget, WebSocket

            target = CdpTarget.from_port(
                port, title_match=self.cdp_titles.get(agent, "")
            )
            if target is None:
                return None, f"cdp: страница не найдена на порту {port}"
            socket_ = WebSocket(target.ws_url, timeout=self.dialog_probe_timeout)
            try:
                socket_.call("Runtime.enable")
                expression = _DIALOG_LABELS_JS.replace(
                    "SELECTOR", _json_string(profile["dialog_selector"])
                )
                result = socket_.call(
                    "Runtime.evaluate",
                    {"expression": expression, "returnByValue": True},
                )
            finally:
                socket_.close()
        except Exception as exc:
            return None, f"cdp: {exc}"
        raw = (result or {}).get("result", {}).get("value")
        if not raw:
            return set(), ""
        try:
            import json

            return {str(x).strip().lower() for x in json.loads(raw)}, ""
        except ValueError as exc:
            return None, f"cdp: нечитаемый ответ ({exc})"

    def addressing(self, session, tab_index: int | None) -> tuple[str, str]:
        """How precisely this session can be hit: `cdp`, `tab`, or `blind`."""
        port, reason = self.cdp_status(session.agent)
        if port:
            return "cdp", f"через отладчик, порт {port}"
        if tab_index:
            return "tab", f"CTRL+{tab_index} в окне агента"
        return "blind", f"вслепую, в открытый чат ({reason})"

    def window_for(self, session):
        # A Session carries the agent; a bare agent name is accepted too,
        # which is what the shipped-window-map test checks.
        agent = session if isinstance(session, str) else session.agent
        return self.targets.get(agent)

    def _wait(self, milliseconds: int) -> None:
        if milliseconds > 0:
            self.sleep(milliseconds / 1000.0)

    def plan(self, session, text: str, tab_index: int | None) -> list[str]:
        target = self.window_for(session)
        described = "?" if target is None else f"{target[0]} / {target[2] or 'any title'}"
        steps = [f"activate {described}"]
        if tab_index:
            steps.append(f"CTRL+{tab_index} (tab of {session.name})")
        steps.append(f"paste {len(text)} chars")
        if self.submit:
            steps.append(self.submit)
        return steps

    def deliver(
        self,
        session,
        text: str,
        tab_index: int | None = None,
        dry: bool = False,
    ) -> DeliveryResult:
        """Deliver once, retrying only what is worth retrying.

        Window work fails for boring, temporary reasons: the app was minimised,
        another window grabbed focus for a moment, the clipboard was held. One
        attempt turns any of those into a stopped batch. A refusal -- empty
        prompt, unknown agent, a CDP sender saying the field is busy -- is not
        transient and is returned immediately.
        """
        attempts = max(1, self.attempts)
        result = self._deliver_once(session, text, tab_index, dry)
        for attempt in range(2, attempts + 1):
            if result.ok or not _is_transient(result.reason):
                return result
            self._wait(self.retry_delay_ms * (attempt - 1))
            retry = self._deliver_once(session, text, tab_index, dry)
            retry.plan = result.plan + [f"попытка {attempt}: {retry.reason}"]
            result = retry
        return result

    def _deliver_once(
        self,
        session,
        text: str,
        tab_index: int | None = None,
        dry: bool = False,
    ) -> DeliveryResult:
        steps = self.plan(session, text, tab_index)
        if not text.strip():
            return DeliveryResult(False, "empty prompt", plan=steps)
        if dry:
            return DeliveryResult(True, "dry run: nothing sent", plan=steps)

        # The debugger first, when the agent offers one. It picks the
        # conversation by name, refuses to type over a half-written message
        # and reads the field back -- none of which keystrokes can do.
        sender = self.sender_for(session.agent)
        if sender is not None:
            cdp_target, why = self._cdp_target(session)
            if cdp_target is not None:
                return self._deliver_over_cdp(session, text, cdp_target, steps, sender)
            steps.append(f"cdp недоступен: {why}")

        target = self.window_for(session)
        if target is None:
            return DeliveryResult(
                False, f"no window mapping for agent {session.agent!r}", plan=steps
            )

        # Keystrokes only. Checked after the CDP branch on purpose: the
        # debugger delivers through a socket and does not care that the screen
        # is locked.
        if not self.desktop_check():
            return DeliveryResult(
                False,
                "рабочий стол заблокирован — клавиши никуда не уйдут "
                "(нужен отладчик или разблокировать)",
                plan=steps,
            )

        exe, window_class, title = target
        if session.agent in WINDOW_PER_PROJECT:
            # One window per workspace, and the workspace name is in the title
            # bar. That is a real address: no tab index to guess, no Ctrl+N
            # that lands in whatever the editor happened to have open.
            title = session.project_name or title
            tab_index = None

        if tab_index is not None and not (1 <= tab_index <= MAX_TAB_INDEX):
            return DeliveryResult(
                False,
                f"tab {tab_index} is out of reach: only CTRL+1..{MAX_TAB_INDEX} exist",
                plan=steps,
            )

        baseline = self._activity_of(session.key)

        try:
            info = self.api.resolve_target(exe, window_class, title)
        except Exception as exc:
            # No window carrying that workspace name. Ask the editor to open it
            # in the window it already has -- `--reuse-window` is the documented
            # contract, and a bare path argument can spawn a second one.
            reopened = self._reuse_window(session)
            if not reopened:
                return DeliveryResult(False, f"window not found: {exc}", plan=steps)
            try:
                info = self.api.resolve_target(exe, window_class, title)
            except Exception as retry_exc:
                return DeliveryResult(
                    False, f"window not found: {retry_exc}", plan=steps
                )

        if not self.api.activate_window(info.hwnd, self.activation_timeout_ms):
            return DeliveryResult(False, "could not activate the window", plan=steps)
        if not self.api.is_foreground(info.hwnd):
            return DeliveryResult(False, "the window lost focus", plan=steps)

        if tab_index:
            self.api.send_combo(f"CTRL+{tab_index}", self.key_delay_ms)
            self._wait(self.settle_ms)
            # Switching tabs can raise a different window (a dialog, a picker).
            # Sending the prompt anyway is how text lands in a stranger's chat.
            if not self.api.is_foreground(info.hwnd):
                return DeliveryResult(
                    False, "focus moved away after the tab switch", plan=steps
                )

        # Clipboard guard (T-052): a paste replaces what the user copied, and
        # the keystroke path must hand it back. Snapshot before the set, put
        # it back once the paste (and submit) is done. The CDP path never
        # touches the clipboard, so it is deliberately left alone.
        activity_before = {}
        if self.activity_map is not None:
            try:
                activity_before = dict(self.activity_map() or {})
            except Exception:
                activity_before = {}
        saved_clipboard = self._snapshot_clipboard()
        if not self.clipboard.set(text):
            return DeliveryResult(False, "could not put the text on the clipboard",
                                  plan=steps)
        try:
            self.api.send_combo("CTRL+V", self.key_delay_ms)
            self._wait(self.settle_ms)

            if self.submit:
                self.api.send_combo(self.submit, self.key_delay_ms)

            confirmed = self._confirm(session.key, baseline)
            if confirmed:
                return DeliveryResult(True, "sent", confirmed=True, plan=steps)
            stray = self._landed_elsewhere(session.key, activity_before)
            if stray:
                # Measured on 2026-08-06: a send aimed at wintage-f1 landed in
                # saisent-69. Blind delivery hits whatever chat is open, and
                # saying which one is the difference between a shrug and a fact.
                return DeliveryResult(
                    False,
                    f"текст ушёл в другую сессию ({stray}), а не в {session.name}",
                    plan=steps,
                )
            # Unconfirmed is not failure: these agents are Chromium windows and a
            # slow turn simply has not touched its transcript yet. Reported as
            # sent-but-unproven so the pane can show the difference.
            return DeliveryResult(
                True, "sent, but the session showed no activity yet", plan=steps
            )
        finally:
            self._restore_clipboard(saved_clipboard)

    def _snapshot_clipboard(self) -> str | None:
        """What the user had copied before this paste, or None when nothing
        text-y was there. A missing `get` (test doubles, older code) means
        nothing to guard -- and nothing to restore."""
        getter = getattr(self.clipboard, "get", None)
        if getter is None:
            return None
        try:
            return getter()
        except Exception:
            return None

    def _restore_clipboard(self, saved: str | None) -> None:
        """Hand the user's clipboard back. Best effort: a failed restore must
        not turn a sent prompt into an error report."""
        if saved is None:
            return
        try:
            self.clipboard.set(saved)
        except Exception:
            pass

    def _deliver_over_cdp(self, session, text, target, steps, sender=None
                          ) -> DeliveryResult:
        """Insert through the debugger. No focus stolen, no keystrokes."""
        sender = sender if sender is not None else self.cdp_sender
        baseline = self._activity_of(session.key)
        intent = SimpleNamespace(text=text, item_id="", skill="")
        try:
            result = sender.send(intent, target)
        except Exception as exc:
            return DeliveryResult(False, f"cdp: {exc}", plan=steps)
        if not getattr(result, "ok", False):
            reason = getattr(result, "reason", "cdp отказал")
            # A `hold` from the CDP sender means the field was busy, not that
            # the target is wrong. Never fall back to blind keystrokes here:
            # the precise transport just told us the user is mid-sentence.
            return DeliveryResult(False, f"cdp: {reason}", plan=steps)
        confirmed = self._confirm(session.key, baseline)
        return DeliveryResult(
            True,
            "sent over the debugger" if confirmed else
            "sent over the debugger, no session activity yet",
            confirmed=confirmed,
            plan=steps,
        )

    def _reuse_window(self, session) -> bool:
        """Ask the editor to bring this workspace up in its existing window.

        Returns False when there is nothing to launch, so the caller reports
        the original "window not found" rather than a second, vaguer error.
        """
        recipe = EDITOR_EXECUTABLES.get(session.agent)
        if recipe is None or not session.project:
            return False
        executable = os.path.expandvars(recipe[0])
        if not os.path.exists(executable):
            return False
        try:
            subprocess.Popen(
                [executable, *recipe[1:], session.project],
                close_fds=True,
            )
        except OSError:
            return False
        # Opening a workspace is slower than switching a tab; the editor has to
        # restore the window and rebuild the panel before it can take a paste.
        self._wait(self.settle_ms + 1200)
        return True

    def _activity_of(self, key: str) -> float:
        if self.activity is None:
            return 0.0
        try:
            return float(self.activity(key) or 0.0)
        except Exception:
            return 0.0

    def _confirm(self, key: str, baseline: float) -> bool:
        """Wait for the session's own store to move past `baseline`."""
        if self.activity is None or self.confirm_timeout <= 0:
            return False
        deadline = self.clock() + self.confirm_timeout
        while self.clock() < deadline:
            if self._activity_of(key) > baseline:
                return True
            self.sleep(0.25)
        return self._activity_of(key) > baseline

    def _landed_elsewhere(self, key: str, before: dict) -> str:
        """Which OTHER session moved, when the intended one did not.

        A blind send goes to whatever chat the agent has open. Reporting that
        as merely "unconfirmed" hides the useful half of the truth: the text
        did arrive, just not where it was aimed. Naming the session turns a
        shrug into something the user can act on.
        """
        if self.activity_map is None or not before:
            return ""
        try:
            after = self.activity_map() or {}
        except Exception:
            return ""
        moved = [
            other
            for other, stamp in after.items()
            if other != key and stamp > before.get(other, 0.0) + 0.5
        ]
        return moved[0] if len(moved) == 1 else ""
