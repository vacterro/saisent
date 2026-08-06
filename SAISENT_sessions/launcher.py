"""Getting the debugger port up without asking the user to babysit it.

Measured, so the options are not guesswork:

* CDP needs `--remote-debugging-port` **at launch**. There is no way to attach
  to a Chromium that was started without it.
* UIA is not a way around that. Waking the accessibility tree with
  `WM_GETOBJECT`/`OBJID_CLIENT` was tried against a running `claude.exe`: the
  tree stayed at 19 elements -- window chrome and three title-bar buttons, no
  document, no edit field. Chromium keeps renderer accessibility off until it
  is launched with `--force-renderer-accessibility` or a real screen reader is
  announced system-wide, and flipping the global screen-reader flag for every
  app on the machine to type one prompt is not a trade worth making.

So the flag has to be there when the app starts, and the only question is who
puts it there. Two answers, in order of how little they ask of the user:

1. **`argv.json`** -- the VS Code family reads permanent Electron arguments
   from `~/.<app>/argv.json`. Write the port once and every future launch
   carries it: the taskbar shortcut, the Start menu, an AHK script, anything.
   Nothing has to know about SAISENT.
2. **A launch command** -- for apps with no `argv.json`, the flag goes on the
   command line, so whatever starts the app has to pass it.

Nothing here ever restarts a running agent. A restart throws away whatever it
was in the middle of, and that is the user's call, never a side effect.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

# Agents whose Electron args can be made permanent, and where that file lives.
ARGV_JSON_PATHS = {
    "antigravity": "~/.antigravity/argv.json",
}

# Default debugger ports. Kept distinct so two agents never collide.
DEFAULT_PORTS = {
    "antigravity": 28194,
    "claude-code": 9222,
    "codenomad": 9223,
    "freebuff": 9224,
}

# Where each agent's executable normally sits. The first hit wins; a miss is
# reported rather than guessed, because launching the wrong binary is worse
# than saying "not found".
EXE_CANDIDATES = {
    "antigravity": (r"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe",),
    # The Squirrel stub first: it survives updates, the versioned folder does
    # not (`app-1.25927.0` today, something else after the next release).
    "claude-code": (
        r"%LOCALAPPDATA%\AnthropicClaude\claude.exe",
        r"%LOCALAPPDATA%\AnthropicClaude\app-*\claude.exe",
    ),
    "codenomad": (
        r"%LOCALAPPDATA%\Programs\CodeNomad\CodeNomad.exe",
        r"V:\___VAC\__P\__SOFT\___CODETOOLS\CodeNomad\CodeNomad.exe",
    ),
    "freebuff": (
        r"%LOCALAPPDATA%\Programs\@codebufffreebuff-desktop\Freebuff.exe",
    ),
}

# `//` comments are legal in argv.json -- VS Code ships it full of them.
_COMMENT = re.compile(r"^\s*//.*$", re.MULTILINE)


@dataclass
class LaunchPlan:
    agent: str
    port: int
    executable: str = ""
    argv_json: str = ""
    error: str = ""

    @property
    def command(self) -> str:
        if not self.executable:
            return ""
        return f'"{self.executable}" --remote-debugging-port={self.port}'

    @property
    def permanent(self) -> bool:
        """Whether the flag can be made to survive every future launch."""
        return bool(self.argv_json)


def find_executable(agent: str) -> str:
    for pattern in EXE_CANDIDATES.get(agent, ()):
        expanded = os.path.expandvars(pattern)
        if "*" in expanded:
            matches = sorted(Path(expanded).parent.parent.glob(
                Path(expanded).parent.name + "/" + Path(expanded).name))
            if matches:
                return str(matches[-1])
            continue
        if os.path.exists(expanded):
            return expanded
    return ""


def argv_json_path(agent: str) -> Path | None:
    raw = ARGV_JSON_PATHS.get(agent)
    return Path(os.path.expanduser(raw)) if raw else None


def plan_for(agent: str, port: int | None = None) -> LaunchPlan:
    path = argv_json_path(agent)
    return LaunchPlan(
        agent=agent,
        port=int(port or DEFAULT_PORTS.get(agent) or 0),
        executable=find_executable(agent),
        argv_json=str(path) if path and path.parent.exists() else "",
    )


def read_argv_json(path: Path) -> dict:
    """Parse an argv.json, comments and all. `{}` when unreadable."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        return json.loads(_COMMENT.sub("", raw)) or {}
    except ValueError:
        return {}


def current_port(agent: str) -> int:
    path = argv_json_path(agent)
    if path is None or not path.exists():
        return 0
    try:
        return int(read_argv_json(path).get("remote-debugging-port") or 0)
    except (TypeError, ValueError):
        return 0


def enable_permanent_port(agent: str, port: int | None = None) -> tuple[bool, str]:
    """Write `remote-debugging-port` into the agent's `argv.json`.

    Returns `(changed, message)`. Comments in the original are dropped -- the
    file is rewritten as plain JSON, which the app parses the same way -- and
    the previous contents are kept beside it as `.saisent.bak` so a bad write
    is one rename away from undone.
    """
    path = argv_json_path(agent)
    if path is None:
        return False, f"{agent}: постоянные аргументы не поддерживаются"
    if not path.parent.exists():
        return False, f"{agent}: нет папки {path.parent}"
    port = int(port or DEFAULT_PORTS.get(agent) or 0)
    if not port:
        return False, f"{agent}: не задан порт"

    data = read_argv_json(path) if path.exists() else {}
    if int(data.get("remote-debugging-port") or 0) == port:
        return False, f"{agent}: порт {port} уже прописан, нужен только перезапуск"
    data["remote-debugging-port"] = port

    try:
        if path.exists():
            backup = path.with_suffix(".json.saisent.bak")
            backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(temp, path)
    except OSError as exc:
        return False, f"{agent}: запись не удалась ({exc})"
    return True, (
        f"{agent}: порт {port} прописан в argv.json. "
        "Подхватится при следующем запуске — чем угодно, хоть скриптом."
    )


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    """Does anything answer on this port? The cheap live check for whether a
    debugger actually came up. Defined here (not in deliver) so the launcher
    never needs to import the deliverer -- and so the detection below can run
    without the whole transport stack."""
    import socket

    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def running_without_debugger(agent: str, probe=None, process_check=None):
    """Detect T-047's exact case: the agent's exe is alive but its CDP port is
    dead -- launched without `--remote-debugging-port`, which cannot be
    attached later. Returns `(detected, exe_name, port)`.

    `probe`/`process_check` are injected for tests; defaults are the real
    socket probe and `discover.process_running`. No exe found or no port
    defined reads as "not detected" -- there is nothing to restart.
    """
    port = int(DEFAULT_PORTS.get(agent) or 0)
    exe = find_executable(agent)
    exe_name = os.path.basename(exe) if exe else ""
    if not exe_name or not port:
        return False, exe_name, port
    if process_check is None:
        from SAISENT_sessions.discover import process_running as process_check
    if not process_check(exe_name):
        return False, exe_name, port
    probe_fn = probe if probe is not None else port_open
    if probe_fn(port):
        return False, exe_name, port
    return True, exe_name, port


def close_gracefully(
    exe_name: str,
    timeout: float = 20.0,
    force_after: bool = True,
    sleep=time.sleep,
    process_check=None,
    post_close=None,
    force=None,
) -> tuple[bool, str]:
    """Close every process of `exe_name`, politely first.

    `taskkill /F` was the whole of this before, and it is the wrong tool for
    an agent: `/F` terminates with no chance to flush state, and `/IM` matches
    the image name, so `claude.exe` takes the desktop app AND every Claude
    Code CLI session with it in one shot. A WM_CLOSE gives each window the
    same shutdown path as clicking the X; force is the fallback, not the plan.

    Returns `(exited, message)`.
    """
    if process_check is None:
        from SAISENT_sessions.discover import process_running as process_check
    if post_close is None:
        post_close = _post_close_to_windows
    if force is None:
        force = _force_kill

    if not process_check(exe_name):
        return True, f"{exe_name}: уже не запущен"

    post_close(exe_name)
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        if not process_check(exe_name):
            return True, f"{exe_name}: закрылся сам"
        sleep(0.5)

    if not force_after:
        return False, f"{exe_name}: не закрылся за {int(timeout)}с, добивать не стал"
    force(exe_name)
    # Even a forced kill is not instant; relaunching into a dying process is
    # how an Electron single-instance lock leaves the app closed entirely.
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if not process_check(exe_name):
            return True, f"{exe_name}: закрыт принудительно"
        sleep(0.5)
    return False, f"{exe_name}: не удалось закрыть"


def _post_close_to_windows(exe_name: str) -> None:
    """WM_CLOSE to every visible top-level window of that executable."""
    if os.name != "nt":  # pragma: no cover - Windows-only path
        return
    import ctypes
    import ctypes.wintypes as wt

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    WM_CLOSE = 0x0010
    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def callback(hwnd, _param):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel32.OpenProcess(0x1000, False, pid.value)
        if not handle:
            return True
        try:
            size = wt.DWORD(260)
            buffer = ctypes.create_unicode_buffer(260)
            if kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(size)
            ):
                if os.path.basename(buffer.value).lower() == exe_name.lower():
                    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        finally:
            kernel32.CloseHandle(handle)
        return True

    user32.EnumWindows(CB(callback), 0)


def _force_kill(exe_name: str) -> None:  # pragma: no cover - shells out
    import subprocess

    try:
        subprocess.run(
            ["taskkill", "/IM", exe_name, "/F"], capture_output=True, timeout=15
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def restart_warning(agent: str) -> str:
    """What the user is actually agreeing to, per agent."""
    if agent == "claude-code":
        return (
            "Все сессии Claude Code закроются — у них общее имя процесса "
            "claude.exe. Незаписанная работа в них пропадёт."
        )
    return "Текущая работа агента прервётся."


def restart_command(agent: str, port: int | None = None) -> str:
    """The relaunch line that carries the debugger flag. Never executed
    automatically -- restarting an agent kills whatever it was doing, so the
    caller (the user-confirmed UI button) owns the kill + relaunch."""
    return plan_for(agent, port).command


def ahk_snippet(agent: str, port: int | None = None) -> str:
    """A line the user can paste straight into the AHK script.

    AHK v2 escapes a quote inside a double-quoted string by doubling it, so
    the path's own quotes have to be `""`. Emitting them singly produced
    `Run(""C:\\...exe" ...)`, which AHK reads as an empty string followed by
    nonsense -- a snippet that looks right and runs nothing.
    """
    plan = plan_for(agent, port)
    if not plan.executable:
        return f"; {agent}: исполняемый файл не найден"
    inner = plan.command.replace('"', '""')
    return f'Run("{inner}")'
