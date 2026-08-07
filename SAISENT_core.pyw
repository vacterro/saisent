from __future__ import annotations

import copy
import ctypes
import ctypes.wintypes as wt
import json
import os
import queue
import re
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Iterable

import tkinter as tk
from tkinter import messagebox, ttk

from SAISENT_watcher.adapter import Adapter as WatcherAdapter
from SAISENT_watcher.adapter import load_adapters
from SAISENT_watcher.cdp import CdpSender, CdpTarget, port_from_file
from SAISENT_watcher.engine import Engine as WatcherEngine
from SAISENT_watcher.limit_scan import read_agent_text_on_disk
from SAISENT_watcher.limits import assume_window, scan_text
from SAISENT_watcher.probes import FileProbe, SqliteProbe
from SAISENT_watcher.queue import QueueItem, SiloQueue
from SAISENT_watcher.queue import load_queues_jsonl, save_queues_jsonl
from SAISENT_watcher.sender import SendLog, SendResult


APP_NAME = "SAISENT"
APP_VERSION = "2.2.0"
CONFIG_PATH = Path(__file__).with_name("SAISENT_GUI.json")  # known-legacy name, not drift
LOG_PATH = Path(__file__).with_name("SAISENT_GUI.log")  # known-legacy name, not drift
PRESETS_PATH = Path(__file__).with_name("SAISENT_PRESETS.json")
WATCHER_STATE_PATH = Path(__file__).with_name("SAISENT_WATCHER.json")
SEND_LOG_PATH = Path(__file__).with_name("SAISENT_WATCHER.log")
ADAPTERS_PATH = Path(__file__).with_name("SAISENT_ADAPTERS.toml")
MUTEX_NAME = "Local\\SAISENT_GUI_COMPACT_SINGLE_INSTANCE_v2"

FIRE_GRACE_SECONDS = 3
CATCHUP_GRACE_SECONDS = 120
REPEAT_RETRY_MINUTES = 5

WINFUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)


# Vintage Golden tokens from the supplied SAIPEN UI specification.
C = {
    "background": "#1A0F05",
    "backgroundSoft": "#1E1408",
    "surface": "#2A1C0A",
    "surfaceRaised": "#362812",
    "surfaceAlt": "#3A2A15",
    "borderDark": "#0E0803",
    "borderHighlight": "#C0A060",
    "borderMuted": "#4A3820",
    "textPrimary": "#D4B87A",
    "textSecondary": "#B09558",
    "textMuted": "#7A6838",
    "accentTeal": "#008080",
    "accentTealDeep": "#004C4C",
    "success": "#4A7A20",
    "warning": "#7A7A20",
    "danger": "#7A2020",
    "selection": "#362812",
    "compareBack": "#0F0A04",
}

DARK = {
    "background": "#0D0D0D",
    "backgroundSoft": "#141414",
    "surface": "#1E1E1E",
    "surfaceRaised": "#2A2A2A",
    "surfaceAlt": "#2E2E2E",
    "borderDark": "#080808",
    "borderHighlight": "#808080",
    "borderMuted": "#3A3A3A",
    "textPrimary": "#CCCCCC",
    "textSecondary": "#999999",
    "textMuted": "#666666",
    "accentTeal": "#007ACC",
    "accentTealDeep": "#004C7A",
    "success": "#3A7A20",
    "warning": "#8A8A20",
    "danger": "#8A2020",
    "selection": "#264F78",
    "compareBack": "#0A0A0A",
}

LIGHT = {
    "background": "#F0F0F0",
    "backgroundSoft": "#E8E8E8",
    "surface": "#FFFFFF",
    "surfaceRaised": "#F5F5F5",
    "surfaceAlt": "#EAEAEA",
    "borderDark": "#A0A0A0",
    "borderHighlight": "#C0C0C0",
    "borderMuted": "#CCCCCC",
    "textPrimary": "#1A1A1A",
    "textSecondary": "#555555",
    "textMuted": "#888888",
    "accentTeal": "#0066CC",
    "accentTealDeep": "#003D7A",
    "success": "#3A7A20",
    "warning": "#8A8A20",
    "danger": "#CC2222",
    "selection": "#CDE0F5",
    "compareBack": "#E0E0E0",
}

THEMES = {"vintage": C, "dark": DARK, "light": LIGHT}

FONT = ("Verdana", 10)
FONT_SMALL = ("Verdana", 9)
FONT_TITLE = ("Verdana", 12, "bold")
FONT_BUTTON = ("Verdana", 9)


# Fixed-width Win32 ABI types.
# Do not use host-dependent c_ulong here: SendInput requires the exact native
# INPUT layout, including the largest union member.
_WORD = ctypes.c_uint16
_DWORD = ctypes.c_uint32
_LONG = ctypes.c_int32
_ULONG_PTR = ctypes.c_size_t


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", _LONG),
        ("dy", _LONG),
        ("mouseData", _DWORD),
        ("dwFlags", _DWORD),
        ("time", _DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", _WORD),
        ("wScan", _WORD),
        ("dwFlags", _DWORD),
        ("time", _DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", _DWORD),
        ("wParamL", _WORD),
        ("wParamH", _WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", _MOUSEINPUT),
        ("ki", _KEYBDINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("type", _DWORD),
        ("u", _INPUT_UNION),
    ]


@dataclass
class ActionStep:
    kind: str
    value: str = ""
    after_ms: int = 0
    enabled: bool = True


def default_steps() -> list[ActionStep]:
    return [
        ActionStep("PRESS", "ENTER", 1000),
        ActionStep("PRESS", "ENTER", 10000),
        ActionStep("PRESS", "ENTER", 1000),

        ActionStep("PRESS", "CTRL+2", 300),
        ActionStep("TEXT", "1", 1000),
        ActionStep("PRESS", "ENTER", 300),
        ActionStep("PRESS", "ENTER", 1000),

        ActionStep("PRESS", "CTRL+3", 1000),
        ActionStep("TEXT", "1", 300),
        ActionStep("PRESS", "ENTER", 300),
        ActionStep("PRESS", "ENTER", 1000),

        ActionStep("PRESS", "CTRL+4", 1000),
        ActionStep("TEXT", "1", 300),
        ActionStep("PRESS", "ENTER", 1000),
        ActionStep("PRESS", "ENTER", 3000),

        ActionStep("PRESS", "CTRL+5", 1000),
        ActionStep("TEXT", "1", 300),
        ActionStep("PRESS", "ENTER", 1000),
        ActionStep("PRESS", "ENTER", 1000),

        ActionStep("MONITOR_OFF", "", 0),
    ]


def parse_steps(raw_steps) -> list[ActionStep]:
    if not isinstance(raw_steps, list):
        return []

    steps: list[ActionStep] = []
    for item in raw_steps:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "PRESS").upper()
        value = str(item.get("value") or "")
        try:
            # Accept int, float and numeric strings; a malformed delay degrades to
            # 0 instead of dropping the whole step.
            after_ms = int(item.get("after_ms") or 0)
        except (TypeError, ValueError):
            after_ms = 0
        # A missing/null enabled flag means "keep the step" (default), not
        # "silently disable it"; a hand-edited string gets the same strict
        # handling as the scalar bool fields. A garbage string conservatively
        # keeps the step enabled rather than silently disabling it.
        raw_enabled = item.get("enabled", True)
        if raw_enabled is None:
            enabled = True
        elif isinstance(raw_enabled, str):
            enabled = raw_enabled.strip().lower() not in {
                "false", "0", "no", "off"
            }
        else:
            enabled = bool(raw_enabled)
        steps.append(
            ActionStep(
                kind=kind,
                value=value,
                after_ms=after_ms,
                enabled=enabled,
            )
        )
    return steps


@dataclass
class AppConfig:
    version: int = 2

    exe_name: str = "claude.exe"
    class_name: str = "Chrome_WidgetWin_1"
    title_contains: str = "Claude"
    activation_timeout_ms: int = 10000
    key_delay_ms: int = 45

    schedule_enabled: bool = False
    schedule_time: str = "22:32"
    run_if_missed: bool = True
    last_schedule_date: str = ""
    repeat_enabled: bool = True
    interval_hours: int = 5
    next_run: str = ""

    hotkeys_enabled: bool = False
    hotkey_run: str = "Ctrl+Alt+F10"
    hotkey_stop: str = "Ctrl+Alt+F11"
    hotkey_show: str = "Ctrl+Alt+F12"

    tray_enabled: bool = False

    steps: list[ActionStep] = field(default_factory=default_steps)

    @classmethod
    def from_dict(cls, raw: dict) -> tuple["AppConfig", bool]:
        migrated = False
        defaults = cls()

        def pick(name: str, cast, fallback):
            """Return the raw field cast safely; on missing/null/garbage keep default."""
            value = raw.get(name, fallback)
            if value is None:
                return fallback
            try:
                if cast is bool:
                    # Accept real booleans plus common hand-edited spellings.
                    if isinstance(value, str):
                        lowered = value.strip().lower()
                        if lowered in {"true", "1", "yes", "on"}:
                            return True
                        if lowered in {"false", "0", "no", "off"}:
                            return False
                        return fallback
                    return bool(value)
                return cast(value)
            except (TypeError, ValueError):
                return fallback

        kwargs = {
            "version": 2,
            "exe_name": pick("exe_name", str, defaults.exe_name),
            "class_name": pick("class_name", str, defaults.class_name),
            "title_contains": pick("title_contains", str, defaults.title_contains),
            "activation_timeout_ms": pick(
                "activation_timeout_ms", int, defaults.activation_timeout_ms
            ),
            "key_delay_ms": pick("key_delay_ms", int, defaults.key_delay_ms),
            "schedule_enabled": pick(
                "schedule_enabled", bool, defaults.schedule_enabled
            ),
            "schedule_time": pick("schedule_time", str, defaults.schedule_time),
            "run_if_missed": pick("run_if_missed", bool, defaults.run_if_missed),
            "last_schedule_date": pick(
                "last_schedule_date", str, defaults.last_schedule_date
            ),
            "repeat_enabled": pick(
                "repeat_enabled", bool, defaults.repeat_enabled
            ),
            "interval_hours": pick(
                "interval_hours", int, defaults.interval_hours
            ),
            "next_run": pick("next_run", str, defaults.next_run),
            "hotkeys_enabled": pick(
                "hotkeys_enabled", bool, defaults.hotkeys_enabled
            ),
            "hotkey_run": pick("hotkey_run", str, defaults.hotkey_run),
            "hotkey_stop": pick("hotkey_stop", str, defaults.hotkey_stop),
            "hotkey_show": pick("hotkey_show", str, defaults.hotkey_show),
            "tray_enabled": pick("tray_enabled", bool, defaults.tray_enabled),
        }

        raw_steps = raw.get("steps")
        if isinstance(raw_steps, list):
            kwargs["steps"] = parse_steps(raw_steps) or default_steps()
        elif isinstance(raw.get("sequence"), str):
            kwargs["steps"] = migrate_legacy_sequence(raw["sequence"])
            migrated = True
        else:
            kwargs["steps"] = default_steps()

        try:
            version = int(raw.get("version", 1) or 1)
        except (TypeError, ValueError):
            version = 1
        if version < 2:
            migrated = True

        return cls(**kwargs), migrated

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    exe_name: str
    class_name: str


def migrate_legacy_sequence(sequence: str) -> list[ActionStep]:
    steps: list[ActionStep] = []

    for raw_line in sequence.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue

        command, _, argument = line.partition(" ")
        command = command.upper()
        argument = argument.strip()

        if command == "WAIT" and argument.isdigit():
            delay = int(argument)
            if steps and steps[-1].after_ms == 0:
                steps[-1].after_ms = delay
            else:
                steps.append(ActionStep("WAIT", str(delay), 0))
        elif command == "PRESS":
            steps.append(ActionStep("PRESS", argument, 0))
        elif command == "TEXT":
            steps.append(ActionStep("TEXT", argument, 0))
        elif command == "MONITOR_OFF":
            steps.append(ActionStep("MONITOR_OFF", "", 0))

    return steps or default_steps()


class _GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("flags", wt.DWORD),
        ("hwndActive", wt.HWND),
        ("hwndFocus", wt.HWND),
        ("hwndCapture", wt.HWND),
        ("hwndMenuOwner", wt.HWND),
        ("hwndMoveSize", wt.HWND),
        ("hwndCaret", wt.HWND),
        ("rcCaret", wt.RECT),
    ]


class WindowsAPI:
    WM_HOTKEY = 0x0312
    WM_QUIT = 0x0012
    WM_SYSCOMMAND = 0x0112
    WM_GETTEXT = 0x000D
    WM_GETTEXTLENGTH = 0x000E
    SC_MONITORPOWER = 0xF170
    HWND_BROADCAST = 0xFFFF

    SW_RESTORE = 9
    SW_SHOW = 5

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004

    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    MOD_SHIFT = 0x0004
    MOD_WIN = 0x0008
    MOD_NOREPEAT = 0x4000

    VK_MAP = {
        "BACKSPACE": 0x08,
        "TAB": 0x09,
        "ENTER": 0x0D,
        "RETURN": 0x0D,
        "SHIFT": 0x10,
        "CTRL": 0x11,
        "CONTROL": 0x11,
        "ALT": 0x12,
        "PAUSE": 0x13,
        "CAPSLOCK": 0x14,
        "ESC": 0x1B,
        "ESCAPE": 0x1B,
        "SPACE": 0x20,
        "PAGEUP": 0x21,
        "PAGEDOWN": 0x22,
        "END": 0x23,
        "HOME": 0x24,
        "LEFT": 0x25,
        "UP": 0x26,
        "RIGHT": 0x27,
        "DOWN": 0x28,
        "PRINTSCREEN": 0x2C,
        "INSERT": 0x2D,
        "DELETE": 0x2E,
        "WIN": 0x5B,
        "LWIN": 0x5B,
        "RWIN": 0x5C,
        "NUMLOCK": 0x90,
        "SCROLLLOCK": 0x91,
        "SEMICOLON": 0xBA,
        "EQUALS": 0xBB,
        "COMMA": 0xBC,
        "MINUS": 0xBD,
        "PERIOD": 0xBE,
        "SLASH": 0xBF,
        "BACKTICK": 0xC0,
        "LBRACKET": 0xDB,
        "BACKSLASH": 0xDC,
        "RBRACKET": 0xDD,
        "QUOTE": 0xDE,
    }

    KEYBDINPUT = _KEYBDINPUT
    INPUT_UNION = _INPUT_UNION
    INPUT = _INPUT

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("SAISENT работает только в Windows.")

        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        expected_input_size = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
        actual_input_size = ctypes.sizeof(self.INPUT)
        if actual_input_size != expected_input_size:
            raise RuntimeError(
                "Неверный Win32 INPUT layout: "
                f"{actual_input_size} bytes, expected {expected_input_size}."
            )

        callback_type = WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        self.ENUM_CALLBACK = callback_type

        self.user32.EnumWindows.argtypes = [callback_type, wt.LPARAM]
        self.user32.EnumWindows.restype = wt.BOOL
        self.user32.IsWindowVisible.argtypes = [wt.HWND]
        self.user32.IsWindowVisible.restype = wt.BOOL
        self.user32.GetWindowTextLengthW.argtypes = [wt.HWND]
        self.user32.GetWindowTextLengthW.restype = ctypes.c_int
        self.user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        self.user32.GetWindowTextW.restype = ctypes.c_int
        self.user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        self.user32.GetClassNameW.restype = ctypes.c_int
        self.user32.GetWindowThreadProcessId.argtypes = [
            wt.HWND,
            ctypes.POINTER(wt.DWORD),
        ]
        self.user32.GetWindowThreadProcessId.restype = wt.DWORD
        self.user32.GetGUIThreadInfo.argtypes = [
            wt.DWORD,
            ctypes.POINTER(_GUITHREADINFO),
        ]
        self.user32.GetGUIThreadInfo.restype = wt.BOOL
        self.user32.SendMessageW.argtypes = [
            wt.HWND,
            wt.UINT,
            wt.WPARAM,
            wt.LPARAM,
        ]
        self.user32.SendMessageW.restype = ctypes.c_ssize_t
        self.user32.GetForegroundWindow.restype = wt.HWND
        self.user32.SetForegroundWindow.argtypes = [wt.HWND]
        self.user32.SetForegroundWindow.restype = wt.BOOL
        self.user32.BringWindowToTop.argtypes = [wt.HWND]
        self.user32.BringWindowToTop.restype = wt.BOOL
        self.user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
        self.user32.ShowWindow.restype = wt.BOOL
        self.user32.IsIconic.argtypes = [wt.HWND]
        self.user32.IsIconic.restype = wt.BOOL
        self.user32.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
        self.user32.AttachThreadInput.restype = wt.BOOL
        self.user32.SetFocus.argtypes = [wt.HWND]
        self.user32.SetFocus.restype = wt.HWND
        self.user32.SwitchToThisWindow.argtypes = [wt.HWND, wt.BOOL]
        self.user32.SwitchToThisWindow.restype = None

        self.user32.SendInput.argtypes = [
            wt.UINT,
            ctypes.POINTER(self.INPUT),
            ctypes.c_int,
        ]
        self.user32.SendInput.restype = wt.UINT

        self.user32.PostMessageW.argtypes = [
            wt.HWND,
            wt.UINT,
            wt.WPARAM,
            wt.LPARAM,
        ]
        self.user32.PostMessageW.restype = wt.BOOL

        self.user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
        self.user32.RegisterHotKey.restype = wt.BOOL
        self.user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
        self.user32.UnregisterHotKey.restype = wt.BOOL
        self.user32.GetMessageW.argtypes = [
            ctypes.POINTER(wt.MSG),
            wt.HWND,
            wt.UINT,
            wt.UINT,
        ]
        self.user32.GetMessageW.restype = wt.BOOL
        self.user32.PostThreadMessageW.argtypes = [
            wt.DWORD,
            wt.UINT,
            wt.WPARAM,
            wt.LPARAM,
        ]
        self.user32.PostThreadMessageW.restype = wt.BOOL
        self.user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.user32.GetAsyncKeyState.restype = ctypes.c_short

        self.kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
        self.kernel32.OpenProcess.restype = wt.HANDLE
        self.kernel32.QueryFullProcessImageNameW.argtypes = [
            wt.HANDLE,
            wt.DWORD,
            wt.LPWSTR,
            ctypes.POINTER(wt.DWORD),
        ]
        self.kernel32.QueryFullProcessImageNameW.restype = wt.BOOL
        self.kernel32.CloseHandle.argtypes = [wt.HANDLE]
        self.kernel32.CloseHandle.restype = wt.BOOL
        self.kernel32.GetCurrentThreadId.restype = wt.DWORD

    def enum_windows(self) -> list[WindowInfo]:
        windows: list[WindowInfo] = []

        @self.ENUM_CALLBACK
        def callback(hwnd: int, _lparam: int) -> bool:
            if not self.user32.IsWindowVisible(hwnd):
                return True

            title = self.get_window_title(hwnd).strip()
            if not title:
                return True

            windows.append(
                WindowInfo(
                    hwnd=int(hwnd),
                    title=title,
                    exe_name=self.get_process_exe(hwnd),
                    class_name=self.get_class_name(hwnd),
                )
            )
            return True

        if not self.user32.EnumWindows(callback, 0):
            raise ctypes.WinError(ctypes.get_last_error())

        windows.sort(key=lambda item: (item.exe_name.lower(), item.title.lower()))
        return windows

    def get_window_title(self, hwnd: int) -> str:
        length = self.user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(max(length + 1, 2))
        self.user32.GetWindowTextW(hwnd, buffer, len(buffer))
        return buffer.value

    def get_class_name(self, hwnd: int) -> str:
        buffer = ctypes.create_unicode_buffer(512)
        self.user32.GetClassNameW(hwnd, buffer, len(buffer))
        return buffer.value

    def get_process_exe(self, hwnd: int) -> str:
        pid = wt.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""

        handle = self.kernel32.OpenProcess(
            self.PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            pid.value,
        )
        if not handle:
            return ""

        try:
            size = wt.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not self.kernel32.QueryFullProcessImageNameW(
                handle,
                0,
                buffer,
                ctypes.byref(size),
            ):
                return ""
            return os.path.basename(buffer.value)
        finally:
            self.kernel32.CloseHandle(handle)

    def resolve_target(
        self,
        exe_name: str,
        class_name: str,
        title_contains: str,
    ) -> WindowInfo:
        exe = exe_name.strip().lower()
        cls = class_name.strip().lower()
        title = title_contains.strip().lower()

        matches: list[WindowInfo] = []
        for info in self.enum_windows():
            if exe and info.exe_name.lower() != exe:
                continue
            if cls and info.class_name.lower() != cls:
                continue
            if title and title not in info.title.lower():
                continue
            matches.append(info)

        selector = (
            f"exe={exe_name!r}, class={class_name!r}, "
            f"title contains={title_contains!r}"
        )

        if not matches:
            raise RuntimeError(f"Целевое окно не найдено: {selector}.")

        if len(matches) == 1:
            return matches[0]

        exact_title = [
            item for item in matches if title and item.title.lower() == title
        ]
        if len(exact_title) == 1:
            return exact_title[0]

        titles = "; ".join(item.title for item in matches[:3])
        raise RuntimeError(
            f"Найдено {len(matches)} подходящих окон. "
            f"Уточни Title contains. Совпадения: {titles}"
        )

    def is_foreground(self, hwnd: int) -> bool:
        return int(self.user32.GetForegroundWindow() or 0) == int(hwnd)

    def activate_window(self, hwnd: int, timeout_ms: int = 10000) -> bool:
        deadline = time.monotonic() + max(timeout_ms, 250) / 1000.0

        while time.monotonic() < deadline:
            if self.is_foreground(hwnd):
                return True

            if self.user32.IsIconic(hwnd):
                self.user32.ShowWindow(hwnd, self.SW_RESTORE)
            else:
                self.user32.ShowWindow(hwnd, self.SW_SHOW)

            foreground = self.user32.GetForegroundWindow()
            current_tid = self.kernel32.GetCurrentThreadId()
            target_tid = self.user32.GetWindowThreadProcessId(hwnd, None)
            foreground_tid = (
                self.user32.GetWindowThreadProcessId(foreground, None)
                if foreground
                else 0
            )

            attached_target = False
            attached_foreground = False

            try:
                if target_tid and target_tid != current_tid:
                    attached_target = bool(
                        self.user32.AttachThreadInput(
                            current_tid,
                            target_tid,
                            True,
                        )
                    )

                if foreground_tid and foreground_tid != current_tid:
                    attached_foreground = bool(
                        self.user32.AttachThreadInput(
                            current_tid,
                            foreground_tid,
                            True,
                        )
                    )

                self.user32.BringWindowToTop(hwnd)
                self.user32.SetForegroundWindow(hwnd)
                self.user32.SetFocus(hwnd)
            finally:
                if attached_foreground:
                    self.user32.AttachThreadInput(
                        current_tid,
                        foreground_tid,
                        False,
                    )
                if attached_target:
                    self.user32.AttachThreadInput(
                        current_tid,
                        target_tid,
                        False,
                    )

            if self.is_foreground(hwnd):
                return True

            # Windows may reject a foreground transition. A harmless ALT tap
            # unlocks it for the current input thread.
            self._send_vk(0x12, key_up=False)
            self._send_vk(0x12, key_up=True)
            self.user32.SetForegroundWindow(hwnd)
            self.user32.BringWindowToTop(hwnd)

            if self.is_foreground(hwnd):
                return True

            try:
                self.user32.SwitchToThisWindow(hwnd, True)
            except OSError:
                pass

            if self.is_foreground(hwnd):
                return True

            time.sleep(0.1)

        return self.is_foreground(hwnd)

    def _send_input(self, inputs: Iterable["WindowsAPI.INPUT"]) -> None:
        items = list(inputs)
        if not items:
            return

        array_type = self.INPUT * len(items)
        array = array_type(*items)

        ctypes.set_last_error(0)
        sent = self.user32.SendInput(
            len(items),
            array,
            ctypes.sizeof(self.INPUT),
        )

        if sent != len(items):
            error_code = ctypes.get_last_error()
            if error_code:
                raise ctypes.WinError(error_code)
            raise OSError(
                "SendInput отправил "
                f"{sent} из {len(items)} событий без кода Win32 error."
            )

    def _vk_input(self, vk: int, key_up: bool = False) -> "WindowsAPI.INPUT":
        flags = self.KEYEVENTF_KEYUP if key_up else 0
        return self.INPUT(
            type=self.INPUT_KEYBOARD,
            ki=self.KEYBDINPUT(
                wVk=vk,
                wScan=0,
                dwFlags=flags,
                time=0,
                dwExtraInfo=0,
            ),
        )

    def _unicode_input(
        self,
        code_unit: int,
        key_up: bool = False,
    ) -> "WindowsAPI.INPUT":
        flags = self.KEYEVENTF_UNICODE
        if key_up:
            flags |= self.KEYEVENTF_KEYUP

        return self.INPUT(
            type=self.INPUT_KEYBOARD,
            ki=self.KEYBDINPUT(
                wVk=0,
                wScan=code_unit,
                dwFlags=flags,
                time=0,
                dwExtraInfo=0,
            ),
        )

    def _send_vk(self, vk: int, key_up: bool = False) -> None:
        self._send_input([self._vk_input(vk, key_up)])

    def key_to_vk(self, key: str) -> int:
        token = key.strip().upper().replace(" ", "")
        if token in self.VK_MAP:
            return self.VK_MAP[token]

        if re.fullmatch(r"F([1-9]|1[0-9]|2[0-4])", token):
            return 0x70 + int(token[1:]) - 1

        if len(token) == 1 and token.isascii() and token.isalnum():
            return ord(token)

        raise ValueError(f"Неизвестная клавиша: {key}")

    def vk_to_token(self, vk: int) -> str | None:
        canonical = {
            0x08: "BACKSPACE",
            0x09: "TAB",
            0x0D: "ENTER",
            0x1B: "ESC",
            0x20: "SPACE",
            0x21: "PAGEUP",
            0x22: "PAGEDOWN",
            0x23: "END",
            0x24: "HOME",
            0x25: "LEFT",
            0x26: "UP",
            0x27: "RIGHT",
            0x28: "DOWN",
            0x2C: "PRINTSCREEN",
            0x2D: "INSERT",
            0x2E: "DELETE",
            0x90: "NUMLOCK",
            0x91: "SCROLLLOCK",
            0xBA: "SEMICOLON",
            0xBB: "EQUALS",
            0xBC: "COMMA",
            0xBD: "MINUS",
            0xBE: "PERIOD",
            0xBF: "SLASH",
            0xC0: "BACKTICK",
            0xDB: "LBRACKET",
            0xDC: "BACKSLASH",
            0xDD: "RBRACKET",
            0xDE: "QUOTE",
        }

        if vk in canonical:
            return canonical[vk]
        if 0x70 <= vk <= 0x87:
            return f"F{vk - 0x70 + 1}"
        if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
            return chr(vk)
        return None

    def normalize_combo(self, expression: str) -> str:
        parts = [part.strip().upper() for part in expression.split("+") if part.strip()]
        if not parts:
            raise ValueError("Комбинация клавиш пустая.")

        aliases = {"CONTROL": "CTRL", "RETURN": "ENTER", "ESCAPE": "ESC"}
        parts = [aliases.get(part, part) for part in parts]

        modifier_names = {"CTRL", "ALT", "SHIFT", "WIN", "LWIN", "RWIN"}
        modifiers: list[str] = []
        main_keys: list[str] = []

        for part in parts:
            self.key_to_vk(part)
            if part in modifier_names:
                modifiers.append(part)
            else:
                main_keys.append(part)

        if not main_keys:
            main_keys = modifiers[-1:]
            modifiers = modifiers[:-1]

        if len(main_keys) != 1:
            raise ValueError(
                f"Допустима одна основная клавиша: {expression!r}."
            )

        order = ["CTRL", "ALT", "SHIFT", "WIN", "LWIN", "RWIN"]
        modifiers = sorted(
            dict.fromkeys(modifiers),
            key=lambda item: order.index(item),
        )
        return "+".join(modifiers + main_keys)

    def send_combo(self, expression: str, key_delay_ms: int = 45) -> None:
        normalized = self.normalize_combo(expression)
        parts = normalized.split("+")

        modifiers = [
            self.key_to_vk(part)
            for part in parts[:-1]
        ]
        main_key = self.key_to_vk(parts[-1])

        inputs: list[WindowsAPI.INPUT] = []
        inputs.extend(self._vk_input(vk, False) for vk in modifiers)
        inputs.append(self._vk_input(main_key, False))
        inputs.append(self._vk_input(main_key, True))
        inputs.extend(self._vk_input(vk, True) for vk in reversed(modifiers))
        self._send_input(inputs)

        if key_delay_ms > 0:
            time.sleep(key_delay_ms / 1000.0)

    def send_text(self, text: str, key_delay_ms: int = 45) -> None:
        data = text.encode("utf-16-le")

        for index in range(0, len(data), 2):
            code_unit = int.from_bytes(data[index : index + 2], "little")
            self._send_input(
                [
                    self._unicode_input(code_unit, False),
                    self._unicode_input(code_unit, True),
                ]
            )
            if key_delay_ms > 0:
                time.sleep(key_delay_ms / 1000.0)

    def focused_child(self, hwnd: int) -> int:
        """The control inside `hwnd` holding keyboard focus.

        Read through GetGUIThreadInfo, which reports another thread's focus
        WITHOUT attaching to it. Returns `hwnd` itself when nothing inside
        holds focus or the read fails.
        """
        info = _GUITHREADINFO()
        info.cbSize = ctypes.sizeof(info)
        tid = self.user32.GetWindowThreadProcessId(hwnd, None)
        if tid and self.user32.GetGUIThreadInfo(tid, ctypes.byref(info)):
            if info.hwndFocus:
                return int(info.hwndFocus)
        return hwnd

    def read_target_text(self, hwnd: int) -> str:
        """What the target's focused input control holds right now.

        The read-back rule the CDP sender enforces: typing successfully is
        not the same as the text landing. Returns '' when the control cannot
        be read (a console host reads through its own path) - the caller
        treats that as "not confirmed", never as proof the text is absent.
        """
        try:
            dest = self.focused_child(hwnd)
            length = int(
                self.user32.SendMessageW(dest, self.WM_GETTEXTLENGTH, 0, 0)
            )
            if length <= 0:
                return ""
            buf = ctypes.create_unicode_buffer(length + 1)
            self.user32.SendMessageW(
                dest, self.WM_GETTEXT, length + 1, buf
            )
            return buf.value
        except Exception:
            return ""

    def monitor_off(self) -> None:
        self.user32.PostMessageW(
            self.HWND_BROADCAST,
            self.WM_SYSCOMMAND,
            self.SC_MONITORPOWER,
            2,
        )

    def parse_hotkey(self, hotkey: str) -> tuple[int, int]:
        normalized = self.normalize_combo(hotkey)
        parts = normalized.split("+")
        modifiers = self.MOD_NOREPEAT
        key_token: str | None = None

        for part in parts:
            if part == "CTRL":
                modifiers |= self.MOD_CONTROL
            elif part == "ALT":
                modifiers |= self.MOD_ALT
            elif part == "SHIFT":
                modifiers |= self.MOD_SHIFT
            elif part in {"WIN", "LWIN", "RWIN"}:
                modifiers |= self.MOD_WIN
            else:
                key_token = part

        if key_token is None:
            raise ValueError(f"Hotkey требует основную клавишу: {hotkey!r}.")

        return modifiers, self.key_to_vk(key_token)

    def pressed_modifiers(self) -> list[str]:
        result: list[str] = []

        if self.user32.GetAsyncKeyState(0x11) & 0x8000:
            result.append("CTRL")
        if self.user32.GetAsyncKeyState(0x12) & 0x8000:
            result.append("ALT")
        if self.user32.GetAsyncKeyState(0x10) & 0x8000:
            result.append("SHIFT")
        if (
            self.user32.GetAsyncKeyState(0x5B) & 0x8000
            or self.user32.GetAsyncKeyState(0x5C) & 0x8000
        ):
            result.append("WIN")

        return result


class RunError(RuntimeError):
    pass


def load_presets() -> dict[str, list[ActionStep]]:
    if not PRESETS_PATH.exists():
        return {}

    try:
        raw = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
    except (OSError, ValueError):
        return {}

    presets: dict[str, list[ActionStep]] = {}
    for name, item in raw.items():
        if not isinstance(item, list):
            continue
        steps = parse_steps(item)
        if steps:
            presets[str(name)] = steps
    return presets


def save_presets(presets: dict[str, list[ActionStep]]) -> bool:
    payload = {
        name: [asdict(step) for step in steps]
        for name, steps in presets.items()
    }
    try:
        atomic_write_json(PRESETS_PATH, payload)
        return True
    except OSError:
        return False


def decode_text(text: str) -> str:
    return (
        text.replace(r"\\", "\0")
        .replace(r"\n", "\n")
        .replace(r"\r", "\r")
        .replace(r"\t", "\t")
        .replace("\0", "\\")
    )


def parse_nonnegative_int(value: str | int, field_name: str) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{field_name}: требуется целое число.")

    if number < 0:
        raise ValueError(f"{field_name}: значение не может быть отрицательным.")

    if number > 86_400_000:
        raise ValueError(
            f"{field_name}: значение больше 24 часов выглядит ошибкой."
        )

    return number


def parse_schedule_time(value: str) -> int:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", value.strip())
    if not match:
        raise ValueError("Время запуска должно быть HH:MM или HH:MM:SS.")

    hour = int(match.group(1))
    minute = int(match.group(2))
    second = int(match.group(3) or 0)

    if hour > 23 or minute > 59 or second > 59:
        raise ValueError("Время запуска должно быть в диапазоне 00:00-23:59.")

    return hour * 3600 + minute * 60 + second


def parse_iso_time(value: str) -> datetime | None:
    if not value or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError:
        return None


def atomic_write_json(path: Path, payload: dict) -> None:
    """Write JSON atomically via a temp file + os.replace so a crash
    mid-write can never leave a truncated SAISENT_GUI.json behind."""
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temp, path)


def _toml_scalar(value) -> str:
    """A scalar as TOML: bools/int as-is, everything else a JSON string."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _toml_inline(value) -> str:
    """A dict/list as a TOML inline value.

    json.dumps would produce `{"type": "assistant"}` — JSON uses `:` where
    TOML inline tables use `=`, so a hand-built string is required.
    """
    if isinstance(value, dict):
        inner = ", ".join(
            f"{key} = {_toml_inline(item)}" for key, item in value.items()
        )
        return "{ " + inner + " }"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_inline(item) for item in value) + "]"
    return _toml_scalar(value)


def _toml_block(block: dict) -> str:
    """Serialize one agent block into TOML text for appending to the
    adapters file (tomllib can read but never write)."""
    keys = (
        "name", "enabled", "settle_ms", "submit", "multiline",
        "skill_format", "blocker_pattern", "transport", "cdp_port",
        "cdp_port_file", "cdp_title", "cdp_selector",
    )
    lines = ["[[agent]]"]
    for key in keys:
        if key in block and block[key] not in (None, ""):
            lines.append(f"{key} = {_toml_scalar(block[key])}")
    for spec in block.get("probe") or ():
        lines.append("  [[agent.probe]]")
        for key, value in spec.items():
            lines.append(f"  {key} = {_toml_inline(value)}")
    return "\n".join(lines)


def scan_installed_agents() -> list[dict]:
    """Find installed CLI agents and their stores on this machine.

    Returns TOML-shaped blocks for adapters whose binary is on PATH and
    whose store exists. A missing agent simply isn't listed — nothing here
    ever claims a store exists that doesn't.
    """
    import glob as _glob
    import shutil

    home = Path.home()
    found: list[dict] = []

    # Claude Code: session jsonl under ~/.claude/projects.
    if shutil.which("claude") and _glob.glob(
        str(home / ".claude" / "projects" / "*" / "*.jsonl")
    ):
        found.append({
            "name": "Claude Code",
            "enabled": True,
            "settle_ms": 2500,
            "submit": "enter",
            "multiline": "join",
            "skill_format": "/{skill} {text}",
            "probe": [{
                "kind": "file",
                "glob": "~/.claude/projects/*/*.jsonl",
                "newest": True,
                "quiet_ms": 2000,
                "last_line_json": {"type": "assistant"},
                "ignore_types": ["custom-title", "ai-title", "mode",
                                  "last-prompt", "queue-operation",
                                  "summary"],
            }],
        })

    # opencode: one shared WAL sqlite store.
    opencode_db = home / ".local" / "share" / "opencode" / "opencode.db"
    if shutil.which("opencode") and opencode_db.exists():
        found.append({
            "name": "opencode",
            "enabled": True,
            "settle_ms": 4000,
            "submit": "enter",
            "multiline": "join",
            "skill_format": "/{skill} {text}",
            "probe": [{
                "kind": "sqlite",
                "path": "~/.local/share/opencode/opencode.db",
                "watch": "wal_mtime",
                "quiet_ms": 4000,
            }],
        })

    # codex: per-session rollout jsonl.
    if shutil.which("codex") and _glob.glob(
        str(home / ".codex" / "sessions" / "*" / "*" / "*" / "rollout-*.jsonl")
    ):
        found.append({
            "name": "codex",
            "enabled": True,
            "settle_ms": 4000,
            "submit": "enter",
            "multiline": "join",
            "skill_format": "/{skill} {text}",
            "probe": [{
                "kind": "file",
                "glob": "~/.codex/sessions/*/*/*/rollout-*.jsonl",
                "newest": True,
                "quiet_ms": 4000,
            }],
        })

    # freebuff: this project's WAL store.
    fb_db = Path(__file__).with_name(".freebuff") / "desktop-v2.db"
    if fb_db.exists():
        found.append({
            "name": "freebuff",
            "enabled": True,
            "settle_ms": 3000,
            "submit": "enter",
            "multiline": "join",
            "skill_format": "/{skill} {text}",
            "transport": "cdp",
            "cdp_port": 9334,
            "probe": [{
                "kind": "sqlite",
                "path": ".freebuff/desktop-v2.db",
                "watch": "wal_mtime",
                "quiet_ms": 2500,
            }],
        })

    # antigravity: per-conversation dbs, sizes are not monotonic.
    if _glob.glob(str(home / ".gemini" / "antigravity" / "conversations" / "*.db*")):
        found.append({
            "name": "antigravity",
            "enabled": True,
            "settle_ms": 4000,
            "submit": "enter",
            "multiline": "join",
            "skill_format": "/{skill} {text}",
            "transport": "cdp",
            "cdp_title": "chat",
            "cdp_port_file": "~/AppData/Roaming/Antigravity/DevToolsActivePort",
            "probe": [{
                "kind": "file",
                "glob": "~/.gemini/antigravity/conversations/*.db*",
                "newest": True,
                "quiet_ms": 4000,
            }],
        })

    # gemini-cli: installed but no moving store known.
    if (home / ".gemini" / "GEMINI.md").exists():
        found.append({
            "name": "gemini-cli",
            "enabled": False,
            "settle_ms": 4000,
            "submit": "enter",
            "multiline": "join",
        })

    return found


def validate_settings(config: AppConfig, api: WindowsAPI) -> None:
    if not (
        config.exe_name.strip()
        or config.class_name.strip()
        or config.title_contains.strip()
    ):
        raise ValueError("Укажи хотя бы один признак целевого окна.")

    if not 250 <= int(config.activation_timeout_ms) <= 60_000:
        raise ValueError("Таймаут активации: допустимо 250-60000 мс.")

    if not 0 <= int(config.key_delay_ms) <= 1000:
        raise ValueError("Задержка клавиш: допустимо 0-1000 мс.")

    if config.schedule_enabled:
        parse_schedule_time(config.schedule_time)
        if config.repeat_enabled:
            if not 1 <= int(config.interval_hours) <= 72:
                raise ValueError("Интервал автоповтора: допустимо 1-72 часа.")

    if config.hotkeys_enabled:
        hotkeys = [
            config.hotkey_run.strip(),
            config.hotkey_stop.strip(),
            config.hotkey_show.strip(),
        ]
        if any(not item for item in hotkeys):
            raise ValueError("Для включённых hotkeys заполни Run, Stop и Show.")
        if len({item.lower() for item in hotkeys}) != 3:
            raise ValueError("Run, Stop и Show hotkeys должны различаться.")
        for item in hotkeys:
            api.parse_hotkey(item)


def validate_config(config: AppConfig, api: WindowsAPI) -> None:
    validate_settings(config, api)

    enabled_steps = [step for step in config.steps if step.enabled]
    if not enabled_steps:
        raise ValueError("Последовательность не содержит включённых действий.")

    for index, step in enumerate(config.steps, start=1):
        if step.kind not in {"PRESS", "TEXT", "WAIT", "MONITOR_OFF"}:
            raise ValueError(f"Шаг {index}: неизвестное действие {step.kind!r}.")

        step.after_ms = parse_nonnegative_int(
            step.after_ms,
            f"Шаг {index}, пауза после",
        )

        if step.kind == "PRESS":
            step.value = api.normalize_combo(step.value)
        elif step.kind == "TEXT":
            if step.value == "":
                raise ValueError(f"Шаг {index}: текст пустой.")
        elif step.kind == "WAIT":
            step.value = str(
                parse_nonnegative_int(step.value, f"Шаг {index}, пауза")
            )
        elif step.kind == "MONITOR_OFF":
            step.value = ""


class SequenceRunner:
    def __init__(
        self,
        api: WindowsAPI,
        on_log: Callable[[str], None],
        on_status: Callable[[str, str], None],
        on_completed: Callable[[bool, str], None] | None = None,
    ) -> None:
        self.api = api
        self.on_log = on_log
        self.on_status = on_status
        self.on_completed = on_completed
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.lock = threading.Lock()

    @property
    def running(self) -> bool:
        return bool(self.worker and self.worker.is_alive())

    def start(self, config: AppConfig, reason: str) -> bool:
        with self.lock:
            if self.running:
                self.on_log("Запуск пропущен: последовательность уже выполняется.")
                return False

            self.stop_event.clear()
            snapshot = copy.deepcopy(config)
            self.worker = threading.Thread(
                target=self._run,
                args=(snapshot, reason),
                name="SAISENT-Runner",
                daemon=True,
            )
            self.worker.start()
            return True

    def stop(self) -> None:
        if self.running:
            self.stop_event.set()
            self.on_log("Запрошена остановка.")
        else:
            self.on_status("IDLE", "Нечего останавливать.")

    def _run(self, config: AppConfig, reason: str) -> None:
        active_steps = [step for step in config.steps if step.enabled]
        self.on_status("RUNNING", f"Запуск: {reason}")
        self.on_log(f"Последовательность запущена ({reason}).")

        try:
            for position, step in enumerate(active_steps, start=1):
                self._check_stop()

                label = self._step_label(step)
                self.on_status(
                    "RUNNING",
                    f"{position}/{len(active_steps)}  {label}",
                )

                if step.kind == "WAIT":
                    duration = int(step.value)
                    self.on_log(f"{position}: пауза {duration} мс")
                    self._wait(duration)

                elif step.kind == "MONITOR_OFF":
                    self.on_log(f"{position}: выключение экранов")
                    self.api.monitor_off()

                else:
                    target = self.api.resolve_target(
                        config.exe_name,
                        config.class_name,
                        config.title_contains,
                    )

                    if not self.api.activate_window(
                        target.hwnd,
                        config.activation_timeout_ms,
                    ):
                        raise RunError(
                            f"Не удалось активировать окно за "
                            f"{config.activation_timeout_ms} мс: {target.title!r}."
                        )

                    if not self.api.is_foreground(target.hwnd):
                        raise RunError(
                            f"Окно потеряло фокус перед шагом {position}; "
                            "ничего не отправлено."
                        )

                    if step.kind == "PRESS":
                        self.on_log(f"{position}: клавиши {step.value}")
                        self.api.send_combo(step.value, config.key_delay_ms)
                    elif step.kind == "TEXT":
                        text = decode_text(step.value)
                        self.on_log(f"{position}: текст {text!r}")
                        self.api.send_text(text, config.key_delay_ms)

                if step.after_ms:
                    self._wait(step.after_ms)

            self.on_status("DONE", "Последовательность выполнена.")
            self.on_log("Последовательность выполнена успешно.")
            self._complete(True, "DONE")

        except Exception as exc:
            state = "STOPPED" if self.stop_event.is_set() else "ERROR"
            self.on_status(state, str(exc))
            self.on_log(f"{state}: {exc}")
            self._complete(False, state)
        finally:
            self.stop_event.clear()

    def _complete(self, success: bool, state: str = "DONE") -> None:
        if self.on_completed is None:
            return
        try:
            self.on_completed(success, state)
        except Exception:
            pass

    def _wait(self, milliseconds: int) -> None:
        deadline = time.monotonic() + milliseconds / 1000.0
        while time.monotonic() < deadline:
            self._check_stop()
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

    def _check_stop(self) -> None:
        if self.stop_event.is_set():
            raise RunError("Остановлено пользователем.")

    @staticmethod
    def _step_label(step: ActionStep) -> str:
        if step.kind == "PRESS":
            return step.value
        if step.kind == "TEXT":
            preview = step.value.replace("\n", r"\n")
            return f"Текст: {preview[:30]}"
        if step.kind == "WAIT":
            return f"Пауза {step.value} мс"
        return "Выключить экраны"


class HotkeyManager:
    IDS = {
        1: "run",
        2: "stop",
        3: "show",
    }

    def __init__(
        self,
        api: WindowsAPI,
        on_action: Callable[[str], None],
        on_message: Callable[[str], None],
    ) -> None:
        self.api = api
        self.on_action = on_action
        self.on_message = on_message
        self.thread: threading.Thread | None = None
        self.thread_id = 0
        self.stop_requested = threading.Event()
        self.mapping: dict[int, str] = {}

    def start(self, config: AppConfig) -> None:
        self.shutdown()

        if not config.hotkeys_enabled:
            self.on_message("Глобальные hotkeys выключены.")
            return

        self.mapping = {
            1: config.hotkey_run,
            2: config.hotkey_stop,
            3: config.hotkey_show,
        }
        self.stop_requested.clear()
        self.thread = threading.Thread(
            target=self._loop,
            name="SAISENT-Hotkeys",
            daemon=True,
        )
        self.thread.start()

    def shutdown(self) -> None:
        self.stop_requested.set()

        if self.thread_id:
            self.api.user32.PostThreadMessageW(
                self.thread_id,
                self.api.WM_QUIT,
                0,
                0,
            )

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)

        self.thread = None
        self.thread_id = 0

    def _loop(self) -> None:
        self.thread_id = int(self.api.kernel32.GetCurrentThreadId())
        registered: list[int] = []

        try:
            for hotkey_id, expression in self.mapping.items():
                action = self.IDS[hotkey_id]
                try:
                    modifiers, vk = self.api.parse_hotkey(expression)
                    ok = self.api.user32.RegisterHotKey(
                        None,
                        hotkey_id,
                        modifiers,
                        vk,
                    )
                    if not ok:
                        raise OSError(
                            f"{expression} уже занят другой программой."
                        )

                    registered.append(hotkey_id)
                    self.on_message(
                        f"Hotkey {action}: {expression}."
                    )
                except Exception as exc:
                    self.on_message(f"Hotkey {action} не включён: {exc}")

            if not registered:
                return

            msg = wt.MSG()
            while not self.stop_requested.is_set():
                result = self.api.user32.GetMessageW(
                    ctypes.byref(msg),
                    None,
                    0,
                    0,
                )
                if result <= 0:
                    break

                if msg.message == self.api.WM_HOTKEY:
                    action = self.IDS.get(int(msg.wParam))
                    if action:
                        self.on_action(action)

        finally:
            for hotkey_id in registered:
                self.api.user32.UnregisterHotKey(None, hotkey_id)


class TrayIcon:
    """System-tray icon via Shell_NotifyIconW — no third-party deps.

    The tray is a hidden message-only window with its own WNDPROC and a
    daemon GetMessage loop (same shape as HotkeyManager), so click events
    never touch the Tk mainloop directly. The state string (watcher/limit)
    is pushed into the tooltip, and a double click restores the window.
    """

    WM_APP = 0x8000
    NIM_ADD = 0
    NIM_MODIFY = 1
    NIM_DELETE = 2
    NIF_MESSAGE = 1
    NIF_ICON = 2
    NIF_TIP = 4
    NIF_INFO = 0x10
    NIIF_NONE = 0x0
    NIIF_INFO = 0x1
    NIIF_WARNING = 0x2
    NIIF_ERROR = 0x3
    WM_LBUTTONUP = 0x0202
    WM_RBUTTONUP = 0x0205
    WM_LBUTTONDBLCLK = 0x0203
    WM_COMMAND = 0x0111
    WM_QUIT = 0x0012
    MENU_SHOW = 1
    MENU_QUIT = 2

    class _NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wt.DWORD),
            ("hWnd", wt.HWND),
            ("uID", wt.UINT),
            ("uFlags", wt.UINT),
            ("uCallbackMessage", wt.UINT),
            ("hIcon", wt.HICON),
            ("szTip", wt.WCHAR * 128),
            ("dwState", wt.DWORD),
            ("dwStateMask", wt.DWORD),
            ("szInfo", wt.WCHAR * 256),
            ("uVersion", wt.UINT),
            ("szInfoTitle", wt.WCHAR * 64),
            ("dwInfoFlags", wt.DWORD),
            ("guidItem", ctypes.c_byte * 16),
            ("hBalloonIcon", wt.HICON),
        ]

    class _WNDCLASSEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wt.UINT),
            ("style", wt.UINT),
            ("lpfnWndProc", ctypes.c_void_p),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wt.HINSTANCE),
            ("hIcon", wt.HICON),
            ("hCursor", wt.HANDLE),
            ("hbrBackground", wt.HANDLE),
            ("lpszMenuName", wt.LPCWSTR),
            ("lpszClassName", wt.LPCWSTR),
            ("hIconSm", wt.HICON),
        ]

    def __init__(
        self,
        user32: ctypes.WinDLL,
        kernel32: ctypes.WinDLL,
        on_restore: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self.user32 = user32
        self.kernel32 = kernel32
        self.on_restore = on_restore
        self.on_quit = on_quit
        self.hwnd = None
        self.thread: threading.Thread | None = None
        self.thread_id = 0
        self.stop_requested = threading.Event()
        self._status = "SAISENT"
        self._visible = False

        # Shell_NotifyIconW lives in shell32, not user32.
        self.shell32 = ctypes.WinDLL("shell32", use_last_error=True)

        _LRESULT = (
            ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8
            else ctypes.c_long
        )
        self._WNDPROC = WINFUNCTYPE(
            _LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM
        )
        self._proc = self._WNDPROC(self._window_proc)
        self.user32.DefWindowProcW.restype = _LRESULT
        self.user32.DefWindowProcW.argtypes = [
            wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM,
        ]
        self.shell32.Shell_NotifyIconW.restype = wt.BOOL
        self.shell32.Shell_NotifyIconW.argtypes = [
            wt.DWORD, ctypes.POINTER(self._NOTIFYICONDATAW),
        ]
        self.user32.LoadIconW.restype = wt.HICON
        self.user32.LoadIconW.argtypes = [wt.HINSTANCE, wt.LPCWSTR]

    # ---- the hidden window -------------------------------------------
    def _register_class(self) -> int:
        class_name = "SAISENT_TRAY_WINDOW"
        wc = self._WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(self._WNDCLASSEXW)
        wc.lpfnWndProc = ctypes.cast(self._proc, ctypes.c_void_p)
        wc.hInstance = self.kernel32.GetModuleHandleW(None)
        wc.lpszClassName = class_name
        atom = self.user32.RegisterClassExW(ctypes.byref(wc))
        if not atom:
            raise ctypes.WinError(ctypes.get_last_error())
        return atom

    def _window_proc(self, hwnd, msg, wparam, lparam):
        if msg == self.WM_APP:
            if lparam in (self.WM_LBUTTONUP, self.WM_LBUTTONDBLCLK):
                self.on_restore()
            elif lparam == self.WM_RBUTTONUP:
                self._show_menu(hwnd)
            return 0
        if msg == self.WM_COMMAND:
            # Выбор пункта меню: wParam — ID пункта (MENU_SHOW / MENU_QUIT).
            command = wparam & 0xFFFF
            if command == self.MENU_SHOW:
                self.on_restore()
            elif command == self.MENU_QUIT:
                self.on_quit()
            return 0
        if msg == self.WM_QUIT:
            return 0
        return self.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _show_menu(self, hwnd) -> None:
        menu = self.user32.CreatePopupMenu()
        if not menu:
            return
        try:
            MF_STRING = 0x0000
            self.user32.AppendMenuW(menu, MF_STRING, self.MENU_SHOW, "Показать окно")
            self.user32.AppendMenuW(menu, MF_STRING, self.MENU_QUIT, "Выход")
            pos = wt.POINT()
            self.user32.GetCursorPos(ctypes.byref(pos))
            self.user32.SetForegroundWindow(hwnd)
            self.user32.TrackPopupMenu(
                menu, 0x0002, pos.x, pos.y, 0, hwnd, None
            )
            self.user32.PostMessageW(hwnd, self.WM_QUIT, 0, 0)
        finally:
            self.user32.DestroyMenu(menu)

    # ---- lifecycle ---------------------------------------------------
    def start(self, status: str = "SAISENT") -> bool:
        if self._visible:
            return True
        try:
            atom = self._register_class()
            self.hwnd = self.user32.CreateWindowExW(
                0,
                atom,
                "SAISENT_TRAY",
                0,
                0, 0, 0, 0,
                None, None,
                self.kernel32.GetModuleHandleW(None),
                None,
            )
            if not self.hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
        except Exception:
            return False

        self.stop_requested.clear()
        self.thread = threading.Thread(
            target=self._loop,
            name="SAISENT-Tray",
            daemon=True,
        )
        self.thread.start()

        nid = self._nid()
        self.shell32.Shell_NotifyIconW(self.NIM_ADD, ctypes.byref(nid))
        self._visible = True
        self.set_status(status)
        return True

    def _nid(self) -> "TrayIcon._NOTIFYICONDATAW":
        nid = self._NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(self._NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = self.NIF_MESSAGE | self.NIF_TIP
        nid.uCallbackMessage = self.WM_APP
        nid.szTip = (self._status or "SAISENT")[:127]
        return nid

    def set_status(self, status: str) -> None:
        self._status = (status or "SAISENT")[:127]
        if not self._visible:
            return
        nid = self._nid()
        self.shell32.Shell_NotifyIconW(self.NIM_MODIFY, ctypes.byref(nid))

    def balloon(self, title: str, text: str, warn: bool = False) -> None:
        """Show a tray balloon (Shell_NotifyIconW NIF_INFO). No-op when hidden.

        A batch finishing at 03:00 used to announce nothing until morning;
        the worker's done event now drives this. `warn` picks the warning icon
        so a run with failures reads differently from a clean one.
        """
        if not self._visible or not self.hwnd:
            return
        nid = self._nid()
        nid.uFlags |= self.NIF_INFO
        nid.szInfoTitle = (title or "")[:63]
        nid.szInfo = (text or "")[:255]
        nid.dwInfoFlags = self.NIIF_WARNING if warn else self.NIIF_INFO
        self.shell32.Shell_NotifyIconW(self.NIM_MODIFY, ctypes.byref(nid))

    def stop(self) -> None:
        self.stop_requested.set()
        if self._visible and self.hwnd:
            nid = self._nid()
            self.shell32.Shell_NotifyIconW(self.NIM_DELETE, ctypes.byref(nid))
            self._visible = False
        if self.thread_id:
            self.user32.PostThreadMessageW(
                self.thread_id, self.WM_QUIT, 0, 0
            )
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        self.thread = None
        self.thread_id = 0
        # Уничтожаем скрытое окно и снимаем класс, чтобы start() мог
        # вызваться снова (иначе RegisterClassExW вернёт ERROR_CLASS_ALREADY_EXISTS
        # и повторное включение трея из _apply_tray молча провалится).
        if self.hwnd:
            self.user32.DestroyWindow(self.hwnd)
            self.user32.UnregisterClassW("SAISENT_TRAY_WINDOW", None)
            self.hwnd = None

    def _loop(self) -> None:
        self.thread_id = int(self.kernel32.GetCurrentThreadId())
        msg = wt.MSG()
        while not self.stop_requested.is_set():
            result = self.user32.GetMessageW(
                ctypes.byref(msg), None, 0, 0
            )
            if result <= 0:
                break
            self.user32.TranslateMessage(ctypes.byref(msg))
            self.user32.DispatchMessageW(ctypes.byref(msg))


class SaisentTarget:
    """What the watcher sends into, re-resolved at send time."""

    __slots__ = ("exe_name", "class_name", "title_contains")

    def __init__(self, exe_name="", class_name="", title_contains=""):
        self.exe_name = exe_name or ""
        self.class_name = class_name or ""
        self.title_contains = title_contains or ""

    @property
    def title(self) -> str:
        # `title` feeds the send log (SendLog.record reads it). A property,
        # not a slot: the target is reconfigured at arm time (watcher_toggle
        # sets title_contains), and the property always reflects that.
        return self.title_contains


class SaisentSender:
    """Types a queued prompt into the configured window via SAISENT's own
    WindowsAPI — the path already proven to work here."""

    dry = False
    silent = False

    def __init__(self, api, submit="ENTER", key_delay_ms=45,
                 activation_timeout_ms=10000, max_unconfirmed=3):
        self.api = api
        self.submit = submit or "ENTER"
        self.key_delay_ms = int(key_delay_ms)
        self.activation_timeout_ms = int(activation_timeout_ms)
        # The read-back rule cdp.py enforces, on the GUI's own post path:
        # typing successfully is not the same as the text landing. After
        # this many UNCONFIRMED sends in a row the hold escalates to a real
        # failure so a dead target surfaces instead of freezing the queue.
        self.max_unconfirmed = max(1, int(max_unconfirmed or 3))
        self._unconfirmed = 0

    def send(self, intent, target):
        if target is None:
            return SendResult(False, "no target configured", intent.text)
        try:
            info = self.api.resolve_target(
                target.exe_name,
                target.class_name,
                target.title_contains,
            )
            if not self.api.activate_window(
                info.hwnd, self.activation_timeout_ms
            ):
                return SendResult(
                    False,
                    "could not activate the target window",
                    intent.text,
                )
            if not self.api.is_foreground(info.hwnd):
                return SendResult(
                    False, "the target lost focus", intent.text
                )
            if intent.text:
                self.api.send_text(intent.text, self.key_delay_ms)
                landed = self.api.read_target_text(info.hwnd)
                if not landed or intent.text not in landed:
                    self._unconfirmed += 1
                    if self._unconfirmed >= self.max_unconfirmed:
                        self._unconfirmed = 0
                        return SendResult(
                            False,
                            f"the target never confirmed {self.max_unconfirmed} "
                            "sends in a row; the text did not land",
                            intent.text,
                        )
                    return SendResult(
                        False,
                        "the text did not reach the field, so nothing was sent",
                        intent.text,
                        hold=True,
                    )
                self._unconfirmed = 0
            if self.submit:
                self.api.send_combo(self.submit, self.key_delay_ms)
            return SendResult(True, "sent", intent.text)
        except Exception as exc:
            return SendResult(False, f"send failed: {exc}", intent.text)


class WatcherController:
    """The copied watcher system driven against SAISENT's own target.

    Owns the engine state machine, the prompt queue, the idle probes and the
    sender. The engine runs on a daemon thread; decisions are reported back
    through injected callbacks so the UI stays responsive.
    """

    def __init__(self, api, on_log, on_status, state_path=None):
        self.api = api
        self.on_log = on_log
        self.on_status = on_status
        self.state_path = Path(state_path or WATCHER_STATE_PATH)
        # The durable per-item store sits beside the state file, so tests
        # that pass a temp state_path never touch the real queue file.
        self.queue_path = self.state_path.with_name(
            self.state_path.stem + ".queue.jsonl")
        self.engine = WatcherEngine()
        # One queue per DIALOG (session), plus the legacy default queue for
        # items that name no dialog. The engine drains one queue per tick;
        # the loop round-robins across the queues that have pending work so
        # no session starves while another's backlog drains.
        self.queue = SiloQueue()
        self.dialog_queues: dict[str, SiloQueue] = {}
        self._dialog_cursor = 0
        self.queue_lock = threading.Lock()
        self.probes: list[FileProbe] = []
        self.sender = SaisentSender(api)
        self.target = SaisentTarget()
        self.send_log = SendLog(limit=500)
        self.send_log_lock = threading.Lock()
        self._load_send_log()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._tick_interval = 0.3
        self._last_status: tuple | None = None
        # Гейт лимита: пока агент говорит "limit reached", промпты держим
        # в очереди и не шлём. `_limit_until` — момент, после которого снова
        # можно отправлять (resets_at из текста, либо assume_window +5ч).
        self.limit_enabled = True
        self._limit_until: datetime | None = None
        self._limit_last_scan = 0.0
        self._limit_rescan_seconds = 15.0
        self._limit_reason = ""
        self._limit_resume_token = None
        # Лок для гейта лимита: `_limit_blocked` крутится в демон-потоке
        # watcher, а `limit_active` вызывается из UI-потока планировщиком
        # расписания. Оба мутируют `_limit_until`/`_limit_resume_token`.
        self._limit_lock = threading.Lock()
        # После прохождения окна лимита даём грейс: очередь должна успеть
        # полностью слиться. Строка «limit reached» в сторе остаётся свежей
        # (<6ч) ещё долго, и повторный скан немедленно заблокировал бы всё
        # снова — один промпт за окно. В грейс не пересканируем вообще.
        self._limit_grace_seconds = 3600.0
        self._limit_grace_until: datetime | None = None
        self.adapter_name = ""
        self.adapter_transport = "post"
        # CDP-настройки адаптера (используются только при transport = "cdp").
        self.cdp_port = 0
        self.cdp_port_file = ""
        self.cdp_title = ""
        self.cdp_selector = ""
        self.cdp_dialog_selector = ""
        self.cdp_dialog_attr = ""
        self._cdp_sender: CdpSender | None = None

    # ---- adapters ----------------------------------------------------
    def apply_adapter(self, adapter: WatcherAdapter) -> bool:
        """Configure the watcher from an adapter block in SAISENT_ADAPTERS.toml.

        The adapter carries the idle probe (file/sqlite/window/process), the
        settle window, the submit key and a transport preference (post/cdp).
        For `post` transport the Win32 sender is used; for `cdp` — the
        DevTools-socket sender, which delivers without stealing focus, and
        only when the debugger port is actually reachable. Returns False when
        the watcher is running (probes must not be swapped mid-run).
        """
        if self.armed:
            return False
        self.adapter_name = adapter.name
        self.adapter_transport = (adapter.transport or "post").lower()
        self.probes = list(adapter.probes)
        self.engine.settle_ms = adapter.settle_ms
        self.sender.submit = (adapter.submit or "ENTER").upper()
        self.cdp_port = adapter.cdp_port
        self.cdp_port_file = adapter.cdp_port_file
        self.cdp_title = adapter.cdp_title
        self.cdp_selector = adapter.cdp_selector
        self.cdp_dialog_selector = adapter.cdp_dialog_selector
        self.cdp_dialog_attr = adapter.cdp_dialog_attr
        if self.adapter_transport == "cdp":
            self._cdp_sender = CdpSender(
                submit=adapter.submit or "enter",
                multiline=adapter.multiline or "join",
                selector=adapter.cdp_selector or "",
                dialog_selector=adapter.cdp_dialog_selector or "",
                dialog_attr=adapter.cdp_dialog_attr or "",
            )
        else:
            self._cdp_sender = None
        self.save_state()
        return True

    def _cdp_target(self):
        """The live debuggable page, or (None, reason)."""
        port = port_from_file(self.cdp_port_file) if self.cdp_port_file else 0
        if not port:
            port = self.cdp_port
        if not port:
            return None, "cdp: не задан порт (cdp_port или cdp_port_file)"
        target = CdpTarget.from_port(port, title_match=self.cdp_title)
        if target is None:
            return None, (
                f"cdp: порт {port} не отвечает или страница не найдена"
            )
        return target, ""

    # ---- persistence ------------------------------------------------
    def load_state(self) -> dict:
        if not self.state_path.exists():
            return {}
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        self.target = SaisentTarget(
            raw.get("exe_name", ""),
            raw.get("class_name", ""),
            raw.get("title_contains", ""),
        )
        self.engine = WatcherEngine(
            settle_ms=raw.get("settle_ms", 2500),
            min_gap_ms=raw.get("min_gap_ms", 4000),
            max_sends=raw.get("max_sends", 25),
        )
        self.limit_enabled = bool(raw.get("limit_enabled", True))
        self.adapter_name = raw.get("adapter_name", "") or ""
        self.adapter_transport = raw.get("adapter_transport", "post") or "post"
        try:
            self.cdp_port = int(raw.get("cdp_port", 0) or 0)
        except (TypeError, ValueError):
            self.cdp_port = 0
        self.cdp_port_file = raw.get("cdp_port_file", "") or ""
        self.cdp_title = raw.get("cdp_title", "") or ""
        self.cdp_selector = raw.get("cdp_selector", "") or ""
        self.cdp_dialog_selector = raw.get("cdp_dialog_selector", "") or ""
        self.cdp_dialog_attr = raw.get("cdp_dialog_attr", "") or ""
        if self.adapter_transport == "cdp":
            self._cdp_sender = CdpSender(
                submit=raw.get("submit", "enter") or "enter",
                multiline=raw.get("multiline", "join") or "join",
                selector=self.cdp_selector or "",
                dialog_selector=self.cdp_dialog_selector or "",
                dialog_attr=self.cdp_dialog_attr or "",
            )
        else:
            self._cdp_sender = None
        items = []
        for entry in raw.get("queue") or ():
            item = QueueItem.from_dict(entry)
            if item is not None:
                items.append(item)
        # The JSONL queue store is the durable one (one line per item, so a
        # crash mid-write cannot lose the whole queue); the embedded "queue"
        # above is the legacy location, read only when the JSONL file is
        # absent. This way a restart keeps every pending prompt.
        queues = load_queues_jsonl(self.queue_path)
        self.dialog_queues = {}
        # Old files used the adapter name as the single slot; new ones
        # use the dialog name. The item's OWN dialog field is the source
        # of truth, so slot keys are ignored and items are grouped by it —
        # including items recovered from the embedded legacy "queue".
        sources = list(queues.values()) if queues else [SiloQueue(items)]
        for silo in sources:
            for item in silo.items:
                if item.dialog:
                    dq = self.dialog_queues.setdefault(
                        item.dialog, SiloQueue())
                    dq.append(item)
                else:
                    self.queue.append(item)
        self.set_probe(
            raw.get("probe_kind", "file"),
            raw.get("glob") or raw.get("path", ""),
            raw.get("quiet_ms", 2000),
            raw.get("watch", "wal_mtime"),
            raw.get("table", ""),
        )
        return raw

    def save_state(self) -> bool:
        payload = {
            "exe_name": self.target.exe_name,
            "class_name": self.target.class_name,
            "title_contains": self.target.title_contains,
            "settle_ms": self.engine.settle_ms,
            "min_gap_ms": self.engine.min_gap_ms,
            "max_sends": self.engine.max_sends,
            "limit_enabled": self.limit_enabled,
            "adapter_name": self.adapter_name,
            "adapter_transport": self.adapter_transport,
            "cdp_port": self.cdp_port,
            "cdp_port_file": self.cdp_port_file,
            "cdp_title": self.cdp_title,
            "cdp_selector": self.cdp_selector,
            "cdp_dialog_selector": self.cdp_dialog_selector,
            "cdp_dialog_attr": self.cdp_dialog_attr,
            "submit": (
                (self._cdp_sender.submit if self._cdp_sender else "enter")
                or "enter"
            ),
            "multiline": (
                (self._cdp_sender.multiline if self._cdp_sender else "join")
                or "join"
            ),
            "probe_kind": self.probes[0].kind if self.probes else "file",
            "glob": (
                self.probes[0].pattern
                if self.probes and self.probes[0].kind == "file" else ""
            ),
            "path": (
                self.probes[0].path
                if self.probes and self.probes[0].kind == "sqlite" else ""
            ),
            "watch": getattr(self.probes[0], "watch", "wal_mtime")
            if self.probes else "wal_mtime",
            "table": getattr(self.probes[0], "table", "")
            if self.probes else "",
            "quiet_ms": self.probes[0].quiet_ms if self.probes else 2000,
            "queue": self.queue.to_list(),
        }
        try:
            atomic_write_json(self.state_path, payload)
        except OSError:
            return False
        # Every state change also lands in the JSONL store, so a restart
        # keeps pending prompts even if the JSON write loses one.
        try:
            store: dict[str, SiloQueue] = {}
            if len(self.queue):
                store[self.adapter_name or "saisent"] = self.queue
            for dialog, silo in self.dialog_queues.items():
                if len(silo):
                    store[dialog] = silo
            save_queues_jsonl(self.queue_path, store)
        except OSError:
            pass
        return True

    def set_probe(self, kind: str, path: str, quiet_ms: int = 2000,
                  watch: str = "wal_mtime", table: str = "") -> None:
        """Configure the idle probe: `file` (glob pattern) or `sqlite`
        (WAL-mtime / max-rowid watch on a database path)."""
        kind = (kind or "file").strip().lower()
        path = (path or "").strip()
        if kind == "sqlite" and path:
            self.probes = [SqliteProbe(path, quiet_ms=quiet_ms,
                                       watch=watch, table=table)]
        elif path:
            self.probes = [FileProbe(path, quiet_ms=quiet_ms,
                                     newest=True)]
        else:
            self.probes = []

    # ---- limit gate --------------------------------------------------
    def _limit_state(self):
        """(reached, resets_at) from the agent's own words, throttled.

        Reads the newest store text via the configured probe and asks
        `limits.scan_text` whether it says "limit reached". Re-scans at most
        every `_limit_rescan_seconds` — reading a store is not free.
        """
        now_mono = time.monotonic()
        if now_mono - self._limit_last_scan < self._limit_rescan_seconds:
            return None
        self._limit_last_scan = now_mono
        if not self.limit_enabled or not self.probes:
            return None
        try:
            adapter = SimpleNamespace(probes=self.probes)
            text = read_agent_text_on_disk(adapter)
        except Exception as exc:
            self.on_log(f"Watcher: проверка лимита не удалась: {exc}")
            return None
        if not text:
            return None
        try:
            state = scan_text(text)
        except Exception as exc:
            self.on_log(f"Watcher: разбор текста лимита не удался: {exc}")
            return None
        return state

    def _probe_token(self):
        """The probe's current signal, used to tell "the agent wrote again"
        from "the store is still sitting on the stale limit line"."""
        for probe in self.probes:
            if getattr(probe, "_last_token", None) is not None:
                return probe._last_token
        return None

    def _limit_blocked(self):
        """(blocked, reason) — should sending be held right now?

        Blocks until `resets_at` (or assumed +5h). After the window passes
        the send is allowed immediately, and the limit is only re-checked
        once the agent actually writes again (probe token changes) — so a
        stale "limit reached" line in the store can not re-block the queue
        for another full day.
        """
        with self._limit_lock:
            return self._limit_blocked_locked()

    def _limit_blocked_locked(self):
        now = datetime.now()
        # Грейс после окна: очередь должна слиться, строку лимита не
        # пересканируем — она может оставаться свежей много часов.
        if self._limit_grace_until is not None:
            if now < self._limit_grace_until:
                return False, ""
            self._limit_grace_until = None

        if self._limit_until is not None:
            if now < self._limit_until:
                return True, self._limit_reason
            # Окно прошло: разблокируем и ждём новой активности агента
            # перед повторным сканом лимита.
            self._limit_until = None
            self._limit_reason = ""
            self._limit_resume_token = self._probe_token()
            self._limit_grace_until = (
                now + timedelta(seconds=self._limit_grace_seconds)
            )
            self.on_log(
                "Watcher: окно лимита прошло, очередь разблокирована. "
                "Повторная проверка лимита через "
                f"{int(self._limit_grace_seconds // 60)} мин."
            )
            return False, ""

        if self._limit_resume_token is not None:
            if self._probe_token() == self._limit_resume_token:
                # агент ничего не писал после сброса: не блокируем
                return False, ""
            self._limit_resume_token = None
            self._limit_last_scan = 0.0   # принудительно свежий скан

        state = self._limit_state()
        if state is None or not state.reached:
            self._limit_resume_token = None
            return False, ""

        resets = state.resets_at or assume_window(hours=5)
        resets += timedelta(seconds=45)
        self._limit_reason = (
            "лимит: жду до "
            f"{resets.strftime('%d.%m %H:%M')}"
        )
        # reason ставим ДО until: между двумя присваиваниями UI-поток
        # может прочитать пару и показать пустую причину (косметика).
        self._limit_until = resets
        self.on_log(
            f"Watcher: лимит исчерпан, отправка остановлена до "
            f"{resets.strftime('%d.%m %H:%M')}."
        )
        return True, self._limit_reason

    def limit_active(self) -> bool:
        """True, если лимит агента сейчас держит отправку.

        Читается планировщиком расписания из UI-потока (в отличие от
        `_limit_blocked`, который крутится в демон-потоке watcher). Под
        общим локом: сканирует стор сам, если гейт ещё не определён —
        расписание уважает лимит даже когда watcher не запущен.
        """
        with self._limit_lock:
            if not self.limit_enabled:
                return False
            if self._limit_until is not None:
                return datetime.now() < self._limit_until
            # Гейт ещё не вычислен: делаем первый (троттлируемый) скан.
            blocked, _reason = self._limit_blocked_locked()
            return blocked

    # ---- queue -------------------------------------------------------
    def add_prompt(self, text: str, dialog: str = "") -> bool:
        """Queue a prompt. When `dialog` names a session, the item goes to
        that session's own queue (and carries the name so the CDP sender can
        select the conversation); an empty dialog lands in the legacy queue
        for whatever is open on the page."""
        text = (text or "").strip()
        dialog = (dialog or "").strip()
        if not text:
            return False
        with self.queue_lock:
            if dialog:
                silo = self.dialog_queues.setdefault(dialog, SiloQueue())
                silo.append(QueueItem(text, dialog=dialog))
            else:
                self.queue.append(QueueItem(text))
        self.save_state()
        return True

    def _flat_items(self):
        """[(key, item)] over every queue, legacy first then dialogs in
        sorted order — the same order `prompts` shows and `remove_prompt`
        indexes. The legacy queue has key ""."""
        rows = [("", item) for item in self.queue.items]
        for dialog in sorted(self.dialog_queues):
            for item in self.dialog_queues[dialog].items:
                rows.append((dialog, item))
        return rows

    def remove_prompt(self, index: int) -> bool:
        with self.queue_lock:
            rows = self._flat_items()
            if not (0 <= index < len(rows)):
                return False
            key, item = rows[index]
            silo = self.queue if key == "" else self.dialog_queues[key]
            silo.remove(item.id)
        self.save_state()
        return True

    def prompts(self) -> list[str]:
        with self.queue_lock:
            return [
                item.text if key == "" else f"[{key}] {item.text}"
                for key, item in self._flat_items()
            ]

    def _pick_queue(self):
        """The queue with pending work for this tick, round-robin across the
        legacy queue and every dialog queue, so one session's backlog never
        starves another. Falls back to the legacy queue when nothing is
        pending — `tick` then reports "nothing left to send"."""
        with self.queue_lock:
            keys = [""] + sorted(self.dialog_queues)
            n = len(keys)
            for i in range(n):
                key = keys[(self._dialog_cursor + i) % n]
                silo = self.queue if key == "" else self.dialog_queues[key]
                if silo.next_pending() is not None:
                    self._dialog_cursor = (self._dialog_cursor + i + 1) % n
                    return silo
        return self.queue

    # ---- arming ------------------------------------------------------
    @property
    def armed(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def arm(self):
        if self.armed:
            return False, "watcher уже запущен"
        if not self.probes:
            return False, "нет пробы бездействия: задай glob"
        self._stop.clear()
        self.engine.arm("saisent", "saisent", self.probes)
        self._last_status = None
        self._limit_until = None
        self._limit_last_scan = 0.0
        self._limit_resume_token = None
        self._limit_grace_until = None
        self._thread = threading.Thread(
            target=self._loop,
            name="SAISENT-Watcher",
            daemon=True,
        )
        self._thread.start()
        self.on_log("Watcher запущен.")
        return True, "watcher запущен"

    def disarm(self, reason="выключен"):
        self._stop.set()
        self.engine.disarm(reason)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    # ---- the loop ----------------------------------------------------
    def _loop(self):
        while not self._stop.is_set():
            now_mono = time.monotonic()
            try:
                blocked, block_reason = self._limit_blocked()
                if blocked:
                    # Промпты не шлём, пока агент в лимите: если движок уже
                    # вернул intent, возвращаем его в очередь (hold) и ждём
                    # следующего тика — после resets_at он уйдёт сам.
                    self.engine.reason = block_reason
                    if self.engine.state == "sending":
                        self.engine.report_held(
                            reason=block_reason, now=now_mono
                        )
                    self._report()
                    self._stop.wait(self._tick_interval)
                    continue

                intent = self.engine.tick(now_mono, self._pick_queue())
                if intent is not None:
                    self._dispatch(intent)
            except Exception as exc:
                self.on_log(f"Watcher tick error: {exc}")
            self._report()
            self._stop.wait(self._tick_interval)

    def _dispatch(self, intent):
        # Отправитель зависит от транспорта адаптера: cdp — тихо через
        # DevTools-сокет (если порт жив), post — Win32-слой SAISENT.
        result = None
        log_target = self.target
        if self.adapter_transport == "cdp":
            # Транспорт cdp означает: агенту нужен DevTools-сокет. При
            # недоступном порте или ненастроенном отправителе НЕ фолбэчим
            # на Win32 — это было бы отправкой в чужое окно. Промпт ждёт.
            if self._cdp_sender is None:
                result = SendResult(
                    False, "cdp: отправитель не настроен", intent.text,
                    hold=True,
                )
            else:
                target, cdp_reason = self._cdp_target()
                if target is None:
                    result = SendResult(
                        False, cdp_reason, intent.text, hold=True
                    )
                else:
                    # The queue item may name the conversation to open;
                    # the sender then selects it before typing.
                    target.dialog = getattr(intent, "dialog", "") or ""
                    result = self._cdp_sender.send(intent, target)
                    log_target = target
        if result is None:
            result = self.sender.send(intent, self.target)
        with self.queue_lock:
            item = self.queue.find(intent.item_id)
            if item is None:
                for silo in self.dialog_queues.values():
                    item = silo.find(intent.item_id)
                    if item is not None:
                        break
        now = time.monotonic()
        if result.ok:
            self.engine.report_sent(item, now=now)
        elif result.hold:
            self.engine.report_held(result.reason, now=now)
        else:
            self.engine.report_failed(item, reason=result.reason, now=now)
        with self.send_log_lock:
            entry = self.send_log.record(intent, result, log_target)
        self._append_send_log(entry)
        self.save_state()
        self.on_log(f"Watcher: {result}")

    # ---- send history -------------------------------------------------
    def _append_send_log(self, entry) -> None:
        try:
            with open(
                Path(SEND_LOG_PATH), "a", encoding="utf-8"
            ) as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _load_send_log(self) -> None:
        path = Path(SEND_LOG_PATH)
        if not path.exists():
            return
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return
        loaded = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict):
                loaded.append(entry)
        if len(loaded) > self.send_log.limit:
            del loaded[:-self.send_log.limit]
        with self.send_log_lock:
            self.send_log.entries = loaded

    def clear_send_log(self) -> None:
        with self.send_log_lock:
            self.send_log.entries = []
        try:
            Path(SEND_LOG_PATH).unlink(missing_ok=True)
        except OSError:
            pass

    def send_history(self, limit: int = 200) -> list[dict]:
        with self.send_log_lock:
            return list(reversed(self.send_log.entries[-limit:]))

    def _report(self):
        status = self.engine.status()
        with self.queue_lock:
            queue_len = len(self.queue)
        key = (status["state"], status["reason"], status["sent"],
               status["failures"], queue_len)
        if key == self._last_status:
            return
        self._last_status = key
        self.on_status(
            status["state"],
            f"{status['reason']} · sent {status['sent']} · "
            f"queue {queue_len}",
        )


def configure_ttk(root: tk.Misc) -> None:
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")

    style.configure(
        "Vintage.TCombobox",
        font=FONT_SMALL,
        foreground=C["textPrimary"],
        fieldbackground=C["compareBack"],
        background=C["surfaceRaised"],
        bordercolor=C["borderDark"],
        lightcolor=C["borderHighlight"],
        darkcolor=C["borderDark"],
        arrowcolor=C["textPrimary"],
        padding=1,
    )
    style.map(
        "Vintage.TCombobox",
        fieldbackground=[
            ("readonly", C["compareBack"]),
            ("disabled", C["surface"]),
        ],
        foreground=[
            ("readonly", C["textPrimary"]),
            ("disabled", C["textMuted"]),
        ],
        selectbackground=[("readonly", C["selection"])],
        selectforeground=[("readonly", C["textPrimary"])],
    )

    style.configure(
        "Vintage.Vertical.TScrollbar",
        background=C["surfaceRaised"],
        troughcolor=C["backgroundSoft"],
        bordercolor=C["borderDark"],
        lightcolor=C["borderHighlight"],
        darkcolor=C["borderDark"],
        arrowcolor=C["textPrimary"],
        gripcount=0,
    )


def vframe(parent: tk.Misc, **kwargs) -> tk.Frame:
    return tk.Frame(parent, bg=C["surfaceRaised"], **kwargs)


def vlabel(
    parent: tk.Misc,
    text: str = "",
    *,
    textvariable: tk.Variable | None = None,
    muted: bool = False,
    small: bool = False,
    anchor: str = "w",
    font: tuple | None = None,
    **kwargs,
) -> tk.Label:
    return tk.Label(
        parent,
        text=text,
        textvariable=textvariable,
        bg=C["surfaceRaised"],
        fg=C["textMuted"] if muted else C["textPrimary"],
        font=font or (FONT_SMALL if small else FONT),
        anchor=anchor,
        **kwargs,
    )


BUTTON_BACKGROUNDS = {
    "normal": C["surfaceRaised"],
    "primary": C["accentTealDeep"],
    "danger": C["danger"],
    "success": C["success"],
}


def style_button(button: tk.Button, role: str = "normal") -> None:
    button.configure(bg=BUTTON_BACKGROUNDS.get(role, C["surfaceRaised"]))


def vbutton(
    parent: tk.Misc,
    text: str,
    command: Callable[[], None],
    *,
    width: int | None = None,
    role: str = "normal",
    state: str = "normal",
) -> tk.Button:
    background = BUTTON_BACKGROUNDS.get(role, C["surfaceRaised"])

    return tk.Button(
        parent,
        text=text,
        command=command,
        width=width,
        height=1,
        padx=5,
        pady=1,
        font=FONT_BUTTON,
        bg=background,
        fg=C["textPrimary"],
        activebackground=C["surfaceAlt"],
        activeforeground=C["textPrimary"],
        disabledforeground=C["textMuted"],
        relief="raised",
        overrelief="raised",
        bd=2,
        highlightthickness=0,
        takefocus=True,
        state=state,
    )


def ventry(
    parent: tk.Misc,
    *,
    textvariable: tk.Variable,
    width: int | None = None,
    state: str = "normal",
) -> tk.Entry:
    return tk.Entry(
        parent,
        textvariable=textvariable,
        width=width,
        font=FONT,
        bg=C["compareBack"],
        fg=C["textPrimary"],
        insertbackground=C["textPrimary"],
        disabledbackground=C["surface"],
        disabledforeground=C["textMuted"],
        selectbackground=C["selection"],
        selectforeground=C["textPrimary"],
        relief="sunken",
        bd=2,
        highlightthickness=0,
        state=state,
    )


def vspinbox(
    parent: tk.Misc,
    *,
    textvariable: tk.Variable,
    width: int = 7,
    from_: int = 0,
    to: int = 86_400_000,
) -> tk.Spinbox:
    return tk.Spinbox(
        parent,
        textvariable=textvariable,
        width=width,
        from_=from_,
        to=to,
        increment=100,
        font=FONT_SMALL,
        bg=C["compareBack"],
        fg=C["textPrimary"],
        buttonbackground=C["surfaceRaised"],
        insertbackground=C["textPrimary"],
        selectbackground=C["selection"],
        selectforeground=C["textPrimary"],
        relief="sunken",
        bd=2,
        highlightthickness=0,
    )


def vcheck(
    parent: tk.Misc,
    *,
    variable: tk.BooleanVar,
    text: str = "",
    command: Callable[[], None] | None = None,
) -> tk.Checkbutton:
    return tk.Checkbutton(
        parent,
        text=text,
        variable=variable,
        command=command,
        font=FONT_SMALL,
        bg=C["surfaceRaised"],
        fg=C["textPrimary"],
        activebackground=C["surfaceRaised"],
        activeforeground=C["textPrimary"],
        selectcolor=C["compareBack"],
        disabledforeground=C["textMuted"],
        highlightthickness=0,
        bd=0,
        padx=0,
        pady=0,
        anchor="w",
    )


class KeyCaptureDialog(tk.Toplevel):
    KEYSYM_MAP = {
        "Return": "ENTER",
        "Escape": "ESC",
        "space": "SPACE",
        "BackSpace": "BACKSPACE",
        "Tab": "TAB",
        "Prior": "PAGEUP",
        "Next": "PAGEDOWN",
        "Home": "HOME",
        "End": "END",
        "Insert": "INSERT",
        "Delete": "DELETE",
        "Left": "LEFT",
        "Right": "RIGHT",
        "Up": "UP",
        "Down": "DOWN",
        "Print": "PRINTSCREEN",
        "Caps_Lock": "CAPSLOCK",
        "Num_Lock": "NUMLOCK",
        "Scroll_Lock": "SCROLLLOCK",
    }

    MODIFIER_KEYSYMS = {
        "Control_L",
        "Control_R",
        "Alt_L",
        "Alt_R",
        "Shift_L",
        "Shift_R",
        "Super_L",
        "Super_R",
        "Win_L",
        "Win_R",
    }

    def __init__(
        self,
        master: tk.Misc,
        api: WindowsAPI,
        initial: str,
        on_apply: Callable[[str], None],
        title: str = "Записать комбинацию",
    ) -> None:
        super().__init__(master)
        self.api = api
        self.on_apply = on_apply
        self.result = initial.strip()

        self.title(title)
        self.geometry("390x150")
        self.resizable(False, False)
        self.configure(bg=C["surfaceRaised"])
        self.transient(master)
        self.grab_set()

        panel = tk.LabelFrame(
            self,
            text=" Нажми нужную комбинацию ",
            font=FONT,
            bg=C["surfaceRaised"],
            fg=C["textPrimary"],
            relief="groove",
            bd=2,
            padx=8,
            pady=8,
        )
        panel.pack(fill="both", expand=True, padx=8, pady=8)

        self.preview_var = tk.StringVar(value=self.result or "...")
        preview = tk.Label(
            panel,
            textvariable=self.preview_var,
            font=FONT_TITLE,
            bg=C["compareBack"],
            fg=C["textPrimary"],
            relief="sunken",
            bd=2,
            anchor="center",
            height=2,
        )
        preview.pack(fill="x")

        button_row = vframe(panel)
        button_row.pack(fill="x", pady=(8, 0))

        vbutton(
            button_row,
            "Применить",
            self.apply,
            role="primary",
        ).pack(side="right")
        vbutton(
            button_row,
            "Отмена",
            self.destroy,
        ).pack(side="right", padx=(0, 5))

        self.bind("<KeyPress>", self.on_key)
        self.after(50, self.focus_force)

    def on_key(self, event: tk.Event) -> str:
        keysym = str(event.keysym)

        if keysym in self.MODIFIER_KEYSYMS:
            return "break"

        token = self.api.vk_to_token(int(event.keycode))
        if token is None:
            token = self.KEYSYM_MAP.get(keysym)

        if token is None:
            if re.fullmatch(r"F([1-9]|1[0-9]|2[0-4])", keysym, re.I):
                token = keysym.upper()
            elif len(keysym) == 1 and keysym.isascii() and keysym.isalnum():
                token = keysym.upper()
            elif len(str(event.char)) == 1 and str(event.char).isascii():
                char = str(event.char)
                punctuation = {
                    ";": "SEMICOLON",
                    "=": "EQUALS",
                    ",": "COMMA",
                    "-": "MINUS",
                    ".": "PERIOD",
                    "/": "SLASH",
                    "`": "BACKTICK",
                    "[": "LBRACKET",
                    "\\": "BACKSLASH",
                    "]": "RBRACKET",
                    "'": "QUOTE",
                }
                token = punctuation.get(char)

        if not token:
            self.bell()
            return "break"

        parts = self.api.pressed_modifiers()
        if token not in {"CTRL", "ALT", "SHIFT", "WIN"}:
            parts.append(token)

        try:
            self.result = self.api.normalize_combo("+".join(parts))
            self.preview_var.set(self.result)
        except Exception:
            self.bell()

        return "break"

    def apply(self) -> None:
        if not self.result:
            self.bell()
            return
        self.on_apply(self.result)
        self.destroy()


class StepRow(tk.Frame):
    DISPLAY_TO_KIND = {
        "Клавиши": "PRESS",
        "Текст": "TEXT",
        "Пауза": "WAIT",
        "Экран выкл.": "MONITOR_OFF",
    }
    KIND_TO_DISPLAY = {value: key for key, value in DISPLAY_TO_KIND.items()}

    def __init__(
        self,
        master: tk.Misc,
        editor: "StepEditor",
        index: int,
        step: ActionStep,
    ) -> None:
        super().__init__(
            master,
            bg=C["surfaceRaised"],
            bd=0,
            highlightthickness=0,
        )
        self.editor = editor
        self.index = index
        self.step = step
        self.initializing = True

        self.enabled_var = tk.BooleanVar(value=step.enabled)
        self.kind_var = tk.StringVar(
            value=self.KIND_TO_DISPLAY.get(step.kind, "Клавиши")
        )
        self.value_var = tk.StringVar(value=step.value)
        self.after_var = tk.StringVar(value=str(step.after_ms))

        self.columnconfigure(3, weight=1)

        vlabel(
            self,
            text=str(index + 1),
            small=True,
            anchor="e",
            width=3,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 2))

        vcheck(
            self,
            variable=self.enabled_var,
            command=self.on_enabled,
        ).grid(row=0, column=1, padx=(0, 4))

        self.kind_combo = ttk.Combobox(
            self,
            textvariable=self.kind_var,
            values=list(self.DISPLAY_TO_KIND.keys()),
            state="readonly",
            width=12,
            font=FONT_SMALL,
            style="Vintage.TCombobox",
        )
        self.kind_combo.grid(row=0, column=2, sticky="ew", padx=(0, 4))
        self.kind_combo.bind("<<ComboboxSelected>>", self.on_kind)

        self.value_entry = ventry(
            self,
            textvariable=self.value_var,
        )
        self.value_entry.grid(row=0, column=3, sticky="ew", padx=(0, 4))

        self.record_button = vbutton(
            self,
            "Запись",
            self.capture_combo,
            width=6,
        )
        self.record_button.grid(row=0, column=4, padx=(0, 4))

        self.after_spin = vspinbox(
            self,
            textvariable=self.after_var,
            width=7,
        )
        self.after_spin.grid(row=0, column=5, padx=(0, 4))

        vbutton(
            self,
            "↑",
            lambda: self.editor.move(self.index, -1),
            width=2,
            state="disabled" if index == 0 else "normal",
        ).grid(row=0, column=6, padx=(0, 2))

        vbutton(
            self,
            "↓",
            lambda: self.editor.move(self.index, 1),
            width=2,
            state=(
                "disabled"
                if index == len(self.editor.steps) - 1
                else "normal"
            ),
        ).grid(row=0, column=7, padx=(0, 2))

        vbutton(
            self,
            "X",
            lambda: self.editor.remove(self.index),
            width=2,
            role="danger",
        ).grid(row=0, column=8)

        self.value_var.trace_add("write", self.on_value)
        self.after_var.trace_add("write", self.on_after)

        self.update_kind_widgets()
        self.initializing = False

    def on_enabled(self) -> None:
        self.step.enabled = bool(self.enabled_var.get())
        self.editor.changed()

    def on_kind(self, _event: tk.Event | None = None) -> None:
        kind = self.DISPLAY_TO_KIND[self.kind_var.get()]
        if kind == self.step.kind:
            return

        self.step.kind = kind
        if kind == "PRESS":
            self.step.value = "ENTER"
            self.step.after_ms = 300
        elif kind == "TEXT":
            self.step.value = ""
            self.step.after_ms = 300
        elif kind == "WAIT":
            self.step.value = "1000"
            self.step.after_ms = 0
        else:
            self.step.value = ""
            self.step.after_ms = 0

        self.editor.changed()
        self.editor.refresh()

    def on_value(self, *_args) -> None:
        if self.initializing:
            return
        self.step.value = self.value_var.get()
        self.editor.changed()

    def on_after(self, *_args) -> None:
        if self.initializing:
            return
        value = self.after_var.get().strip()
        if re.fullmatch(r"\d+", value):
            self.step.after_ms = int(value)
        self.editor.changed()

    def update_kind_widgets(self) -> None:
        kind = self.step.kind

        if kind == "PRESS":
            self.value_entry.configure(state="normal")
            self.record_button.configure(state="normal")
        elif kind == "TEXT":
            self.value_entry.configure(state="normal")
            self.record_button.configure(state="disabled")
        elif kind == "WAIT":
            self.value_entry.configure(state="normal")
            self.record_button.configure(state="disabled")
        else:
            self.value_var.set("Без параметров")
            self.value_entry.configure(state="disabled")
            self.record_button.configure(state="disabled")

    def capture_combo(self) -> None:
        KeyCaptureDialog(
            self,
            self.editor.api,
            self.step.value,
            self.apply_captured_combo,
        )

    def apply_captured_combo(self, combo: str) -> None:
        self.step.value = combo
        self.value_var.set(combo)
        self.editor.changed()


class StepEditor(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        api: WindowsAPI,
        on_change: Callable[[], None],
        on_preset_save: Callable[[], None] | None = None,
        on_preset_load: Callable[[], None] | None = None,
        on_preset_delete: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            master,
            bg=C["surfaceRaised"],
            relief="groove",
            bd=2,
        )
        self.api = api
        self.on_change = on_change
        self.steps: list[ActionStep] = []
        self.rows: list[StepRow] = []

        toolbar = vframe(self)
        toolbar.pack(fill="x", padx=4, pady=4)

        vlabel(
            toolbar,
            text="Действия",
            font=FONT_TITLE,
        ).pack(side="left", padx=(0, 8))

        vbutton(
            toolbar,
            "+ Клавиши",
            lambda: self.add("PRESS"),
        ).pack(side="left", padx=(0, 3))

        vbutton(
            toolbar,
            "+ Текст",
            lambda: self.add("TEXT"),
        ).pack(side="left", padx=(0, 3))

        vbutton(
            toolbar,
            "+ Пауза",
            lambda: self.add("WAIT"),
        ).pack(side="left", padx=(0, 3))

        vbutton(
            toolbar,
            "+ Экран",
            lambda: self.add("MONITOR_OFF"),
        ).pack(side="left")

        vlabel(
            toolbar,
            text="Пресет:",
            muted=True,
            small=True,
        ).pack(side="left", padx=(12, 4))

        self.preset_var = tk.StringVar()
        self.preset_combo = ttk.Combobox(
            toolbar,
            textvariable=self.preset_var,
            values=[],
            state="normal",
            width=14,
            font=FONT_SMALL,
            style="Vintage.TCombobox",
        )
        self.preset_combo.pack(side="left")

        if on_preset_save:
            vbutton(
                toolbar,
                "Сохр.",
                on_preset_save,
                width=6,
            ).pack(side="left", padx=(4, 0))
        if on_preset_load:
            vbutton(
                toolbar,
                "Загрузить",
                on_preset_load,
                width=9,
            ).pack(side="left", padx=(3, 0))
        if on_preset_delete:
            vbutton(
                toolbar,
                "Удал.",
                on_preset_delete,
                width=6,
                role="danger",
            ).pack(side="left", padx=(3, 0))

        header = vframe(self)
        header.pack(fill="x", padx=4, pady=(0, 2))
        header.columnconfigure(3, weight=1)

        vlabel(header, text="#", muted=True, small=True, width=3, anchor="e").grid(
            row=0, column=0, padx=(0, 2)
        )
        vlabel(header, text="", muted=True, small=True, width=2).grid(
            row=0, column=1, padx=(0, 4)
        )
        vlabel(header, text="Тип", muted=True, small=True, width=13).grid(
            row=0, column=2, sticky="w", padx=(0, 4)
        )
        vlabel(
            header,
            text="Значение / комбинация",
            muted=True,
            small=True,
        ).grid(row=0, column=3, sticky="w", padx=(0, 4))
        vlabel(header, text="", muted=True, small=True, width=7).grid(
            row=0, column=4, padx=(0, 4)
        )
        vlabel(header, text="После, мс", muted=True, small=True, width=8).grid(
            row=0, column=5, padx=(0, 4)
        )
        vlabel(header, text="", muted=True, small=True, width=9).grid(
            row=0, column=6, columnspan=3
        )

        body = vframe(self)
        body.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        self.canvas = tk.Canvas(
            body,
            bg=C["backgroundSoft"],
            bd=0,
            highlightthickness=0,
            height=250,
        )
        self.scrollbar = ttk.Scrollbar(
            body,
            orient="vertical",
            command=self.canvas.yview,
            style="Vintage.Vertical.TScrollbar",
        )
        self.inner = vframe(self.canvas)
        self.window_id = self.canvas.create_window(
            (0, 0),
            window=self.inner,
            anchor="nw",
        )

        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.inner.bind("<Configure>", self.on_inner_configure)
        self.canvas.bind("<Configure>", self.on_canvas_configure)
        self.canvas.bind("<Enter>", self.bind_wheel)
        self.canvas.bind("<Leave>", self.unbind_wheel)

    def load_steps(self, steps: list[ActionStep]) -> None:
        self.steps = steps
        self.refresh()

    def set_presets(self, names: list[str]) -> None:
        self.preset_combo.configure(values=names)
        if self.preset_var.get() not in names:
            self.preset_var.set("")

    def refresh(self) -> None:
        position = self.canvas.yview()[0] if self.canvas.winfo_exists() else 0.0

        for child in self.inner.winfo_children():
            child.destroy()

        self.rows.clear()

        if not self.steps:
            vlabel(
                self.inner,
                text="Нет действий. Добавь первое кнопками сверху.",
                muted=True,
            ).pack(anchor="w", padx=6, pady=8)
        else:
            for index, step in enumerate(self.steps):
                row = StepRow(self.inner, self, index, step)
                row.pack(fill="x", padx=2, pady=1)
                self.rows.append(row)

        self.after_idle(lambda: self.canvas.yview_moveto(position))

    def add(self, kind: str) -> None:
        defaults = {
            "PRESS": ActionStep("PRESS", "ENTER", 300),
            "TEXT": ActionStep("TEXT", "", 300),
            "WAIT": ActionStep("WAIT", "1000", 0),
            "MONITOR_OFF": ActionStep("MONITOR_OFF", "", 0),
        }
        self.steps.append(defaults[kind])
        self.changed()
        self.refresh()
        self.after_idle(lambda: self.canvas.yview_moveto(1.0))

    def remove(self, index: int) -> None:
        if index < 0 or index >= len(self.steps):
            return
        del self.steps[index]
        self.changed()
        self.refresh()

    def move(self, index: int, direction: int) -> None:
        target = index + direction
        if not (0 <= index < len(self.steps) and 0 <= target < len(self.steps)):
            return
        self.steps[index], self.steps[target] = self.steps[target], self.steps[index]
        self.changed()
        self.refresh()

    def changed(self) -> None:
        self.on_change()

    def on_inner_configure(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def bind_wheel(self, _event: tk.Event) -> None:
        self.canvas.bind_all("<MouseWheel>", self.on_mousewheel)

    def unbind_wheel(self, _event: tk.Event) -> None:
        self.canvas.unbind_all("<MouseWheel>")

    def on_mousewheel(self, event: tk.Event) -> str:
        delta = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(delta, "units")
        return "break"


class WindowPicker(tk.Toplevel):
    def __init__(self, master: "SAISENTApp", api: WindowsAPI) -> None:
        super().__init__(master)
        self.master_app = master
        self.api = api
        self.windows: list[WindowInfo] = []
        self.visible_windows: list[WindowInfo] = []

        self.title("Выбрать окно")
        self.geometry("720x380")
        self.minsize(600, 320)
        self.configure(bg=C["surfaceRaised"])
        self.transient(master)
        self.grab_set()

        root = vframe(self)
        root.pack(fill="both", expand=True, padx=8, pady=8)

        top = vframe(root)
        top.pack(fill="x", pady=(0, 5))

        vlabel(top, text="Фильтр").pack(side="left")
        self.filter_var = tk.StringVar()
        filter_entry = ventry(top, textvariable=self.filter_var)
        filter_entry.pack(side="left", fill="x", expand=True, padx=5)

        vbutton(top, "Обновить", self.refresh).pack(side="left")

        self.listbox = tk.Listbox(
            root,
            font=FONT_SMALL,
            bg=C["compareBack"],
            fg=C["textPrimary"],
            selectbackground=C["selection"],
            selectforeground=C["textPrimary"],
            relief="sunken",
            bd=2,
            highlightthickness=0,
            activestyle="none",
        )
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<Double-1>", lambda _event: self.apply())

        bottom = vframe(root)
        bottom.pack(fill="x", pady=(5, 0))

        self.count_var = tk.StringVar()
        vlabel(
            bottom,
            textvariable=self.count_var,
            muted=True,
            small=True,
        ).pack(side="left")

        vbutton(
            bottom,
            "Выбрать",
            self.apply,
            role="primary",
        ).pack(side="right")
        vbutton(
            bottom,
            "Отмена",
            self.destroy,
        ).pack(side="right", padx=(0, 5))

        self.filter_var.trace_add("write", lambda *_args: self.render())
        self.refresh()
        filter_entry.focus_set()

    def refresh(self) -> None:
        try:
            self.windows = self.api.enum_windows()
            self.render()
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self)

    def render(self) -> None:
        needle = self.filter_var.get().strip().lower()
        self.visible_windows = []
        self.listbox.delete(0, "end")

        for info in self.windows:
            haystack = f"{info.title} {info.exe_name} {info.class_name}".lower()
            if needle and needle not in haystack:
                continue

            self.visible_windows.append(info)
            self.listbox.insert(
                "end",
                f"{info.title}  |  {info.exe_name}  |  {info.class_name}",
            )

        self.count_var.set(f"Окон: {len(self.visible_windows)}")

    def apply(self) -> None:
        selection = self.listbox.curselection()
        if not selection:
            messagebox.showwarning(
                APP_NAME,
                "Сначала выбери окно.",
                parent=self,
            )
            return

        info = self.visible_windows[int(selection[0])]
        self.master_app.set_target(info)
        self.destroy()


class LogDialog(tk.Toplevel):
    def __init__(self, master: "SAISENTApp") -> None:
        super().__init__(master)
        self.title("Журнал")
        self.geometry("700x560")
        self.minsize(560, 280)
        self.configure(bg=C["surfaceRaised"])
        self.transient(master)

        root = vframe(self)
        root.pack(fill="both", expand=True, padx=8, pady=8)

        self.text = tk.Text(
            root,
            font=FONT_SMALL,
            bg=C["compareBack"],
            fg=C["textPrimary"],
            insertbackground=C["textPrimary"],
            selectbackground=C["selection"],
            selectforeground=C["textPrimary"],
            relief="sunken",
            bd=2,
            highlightthickness=0,
            wrap="word",
            state="disabled",
        )
        self.text.pack(fill="both", expand=True)

        buttons = vframe(root)
        buttons.pack(fill="x", pady=(5, 0))

        vbutton(
            buttons,
            "Обновить",
            self.refresh,
        ).pack(side="left")

        vbutton(
            buttons,
            "Закрыть",
            self.destroy,
        ).pack(side="right")

        self.refresh()

    def refresh(self) -> None:
        try:
            content = (
                LOG_PATH.read_text(encoding="utf-8")
                if LOG_PATH.exists()
                else "Журнал пока пуст."
            )
        except OSError as exc:
            content = f"Не удалось прочитать журнал:\n{exc}"

        lines = content.splitlines()[-300:]
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", "\n".join(lines))
        self.text.configure(state="disabled")
        self.text.see("end")


class SAISENTApp(tk.Tk):
    STATUS_COLORS = {
        "IDLE": C["textSecondary"],
        "RUNNING": C["warning"],
        "DONE": C["success"],
        "STOPPED": C["warning"],
        "ERROR": C["danger"],
        "SAVED": C["success"],
    }

    def __init__(self, api: WindowsAPI) -> None:
        super().__init__()
        self.api = api
        self.ui_queue: queue.Queue[tuple[str, ...]] = queue.Queue()
        self.closing = False
        self.dirty = False
        self.first_tick = True
        self._scheduled_fire_base: datetime | None = None
        self._pending_fire = False
        self._limit_gate_was_active = False
        self._force_quit = False

        self.config, migrated, load_error = self.load_config()
        self.saved_config = copy.deepcopy(self.config)

        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("760x640")
        self.minsize(700, 560)
        self.configure(bg=C["background"])
        configure_ttk(self)

        self._build_ui()
        self.editor.load_steps(self.config.steps)
        self.refresh_preset_ops()
        self.update_summaries()
        self.set_dirty(False)

        self.runner = SequenceRunner(
            self.api,
            self.thread_log,
            self.thread_status,
            self.thread_completed,
        )
        
        self.tray = TrayIcon(
            self.api.user32,
            self.api.kernel32,
            self._tray_restore,
            self._tray_quit,
        )
        self._apply_tray()

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(500, self.process_ui_queue)
        self.after(500, self.scheduler_tick)

        if load_error:
            self.set_status("ERROR", load_error)
            self.log(load_error)
        elif migrated:
            self.set_status(
                "IDLE",
                "Старый raw-конфиг преобразован в визуальные шаги. Сохрани.",
            )
            self.set_dirty(True)
        else:
            self.set_status("IDLE", "Готово.")

        self.log("SAISENT запущен.")

    def _build_ui(self) -> None:
        root = tk.Frame(self, bg=C["background"])
        root.pack(fill="both", expand=True, padx=8, pady=8)

        # Hidden frame for unused components to avoid AttributeErrors
        hidden_root = tk.Frame(self)
        self._build_target_group(hidden_root)
        self._build_schedule_group(hidden_root)
        
        # Hotkeys are not built, but the variables need to exist for config?
        # Let's check if hotkey_run_var is needed
        self.hotkeys_enabled_var = tk.BooleanVar(value=self.config.hotkeys_enabled)
        self.hotkey_run_var = tk.StringVar(value=self.config.hotkey_run)
        self.hotkey_stop_var = tk.StringVar(value=self.config.hotkey_stop)
        self.hotkey_show_var = tk.StringVar(value=self.config.hotkey_show)

        self._build_watcher_group(root)

        self.editor = StepEditor(
            hidden_root,
            self.api,
            self.mark_dirty,
            on_preset_save=self.preset_save,
            on_preset_load=self.preset_load,
            on_preset_delete=self.preset_delete,
        )
        
        self._build_bottom(root)

    def group(self, parent: tk.Misc, text: str) -> tk.LabelFrame:
        return tk.LabelFrame(
            parent,
            text=text,
            font=FONT,
            bg=C["surfaceRaised"],
            fg=C["textPrimary"],
            relief="groove",
            bd=2,
            padx=6,
            pady=6,
        )

    def _build_target_group(self, root: tk.Misc) -> None:
        group = self.group(root, " Целевое окно ")
        group.pack(fill="x")

        row = vframe(group)
        row.pack(fill="x")

        self.target_summary_var = tk.StringVar()
        tk.Label(
            row,
            textvariable=self.target_summary_var,
            font=FONT,
            bg=C["compareBack"],
            fg=C["textPrimary"],
            relief="sunken",
            bd=2,
            anchor="w",
            padx=4,
        ).pack(side="left", fill="x", expand=True)
        vbutton(row, "Выбрать", self.pick_window).pack(side="left", padx=(5, 0))
        vbutton(row, "Проверить", self.test_activation).pack(side="left", padx=(3, 0))

        advanced = vframe(group)
        # advanced.pack(fill="x", pady=(5, 0))

        vlabel(advanced, text="Таймаут активации, мс", small=True).pack(side="left")
        self.timeout_var = tk.StringVar(value=str(self.config.activation_timeout_ms))
        ventry(advanced, textvariable=self.timeout_var, width=7).pack(
            side="left", padx=(5, 12)
        )

        vlabel(advanced, text="Задержка клавиши, мс", small=True).pack(side="left")
        self.key_delay_var = tk.StringVar(value=str(self.config.key_delay_ms))
        ventry(advanced, textvariable=self.key_delay_var, width=6).pack(
            side="left", padx=(5, 0)
        )

        self.timeout_var.trace_add("write", lambda *_args: self.mark_dirty())
        self.key_delay_var.trace_add("write", lambda *_args: self.mark_dirty())

    def _build_schedule_group(self, root: tk.Misc) -> None:
        group = self.group(root, " Расписание ")
        group.pack(fill="x", pady=(7, 0))

        row = vframe(group)
        row.pack(fill="x")

        vlabel(row, text="Ежедневно в").pack(side="left")
        self.schedule_time_var = tk.StringVar(value=self.config.schedule_time)
        ventry(row, textvariable=self.schedule_time_var, width=9).pack(
            side="left", padx=(5, 10)
        )

        self.arm_button = vbutton(
            row,
            "ЗАПУСТИТЬ ПО РАСПИСАНИЮ",
            self.toggle_schedule,
            role="primary",
            width=23,
        )
        self.arm_button.pack(side="left")

        self.run_now_button = vbutton(
            row,
            "Запустить сейчас",
            self.run_now,
            width=16,
        )
        self.run_now_button.pack(side="left", padx=(6, 0))

        repeat = vframe(group)
        repeat.pack(fill="x", pady=(5, 0))

        self.repeat_var = tk.BooleanVar(value=self.config.repeat_enabled)
        vcheck(
            repeat,
            variable=self.repeat_var,
            text="Автоповтор после срабатывания через",
            command=self.mark_dirty,
        ).pack(side="left")

        self.interval_var = tk.StringVar(value=str(self.config.interval_hours))
        ventry(repeat, textvariable=self.interval_var, width=4).pack(
            side="left", padx=(6, 3)
        )
        self.interval_var.trace_add("write", lambda *_args: self.mark_dirty())

        vlabel(repeat, text="часов", small=True).pack(side="left")

        note = vframe(group)
        note.pack(fill="x", pady=(5, 0))

        self.missed_var = tk.BooleanVar(value=self.config.run_if_missed)
        vcheck(
            note,
            variable=self.missed_var,
            text="Выполнить при запуске программы, если время пропущено",
            command=self.mark_dirty,
        ).pack(side="left")

        self.countdown_var = tk.StringVar()
        tk.Label(
            note,
            textvariable=self.countdown_var,
            font=FONT_SMALL,
            bg=C["surfaceRaised"],
            fg=C["textSecondary"],
            anchor="e",
            width=30,
        ).pack(side="right")

    def _build_hotkeys_group(self, root: tk.Misc) -> None:
        group = self.group(root, " Глобальные клавиши ")
        group.pack(fill="x", pady=(7, 0))

        self.hotkeys_enabled_var = tk.BooleanVar(value=self.config.hotkeys_enabled)
        vcheck(
            group,
            variable=self.hotkeys_enabled_var,
            text="Включить",
            command=self.mark_dirty,
        ).grid(row=0, column=0, columnspan=9, sticky="w")

        self.hotkey_run_var = tk.StringVar(value=self.config.hotkey_run)
        self.hotkey_stop_var = tk.StringVar(value=self.config.hotkey_stop)
        self.hotkey_show_var = tk.StringVar(value=self.config.hotkey_show)

        self._hotkey_row(group, 1, "Run", self.hotkey_run_var)
        self._hotkey_row(group, 2, "Stop", self.hotkey_stop_var)
        self._hotkey_row(group, 3, "Show", self.hotkey_show_var)

        for variable in (
            self.hotkey_run_var,
            self.hotkey_stop_var,
            self.hotkey_show_var,
        ):
            variable.trace_add("write", lambda *_args: self.mark_dirty())

    def _hotkey_row(
        self,
        parent: tk.Misc,
        row: int,
        label: str,
        variable: tk.StringVar,
    ) -> None:
        column = (row - 1) * 3
        vlabel(parent, text=label, small=True, width=6).grid(
            row=row,
            column=column,
            sticky="w",
            pady=1,
        )
        ventry(parent, textvariable=variable, width=10).grid(
            row=row,
            column=column + 1,
            sticky="ew",
            padx=(5, 4),
            pady=1,
        )
        vbutton(
            parent,
            "Запись",
            lambda var=variable: self.capture_hotkey(var),
            width=6,
        ).grid(row=row, column=column + 2, pady=1)
        parent.columnconfigure(column + 1, weight=1)

    def get_watcher(self, name: str):
        if not hasattr(self, "watchers"):
            self.watchers = {}
        if name not in self.watchers:
            import re
            safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
            w = WatcherController(
                self.api,
                self.thread_log,
                lambda state, msg, n=name: self.ui_queue.put(("watcher_status", n, state, msg))
            )
            w.state_path = Path(f"SAISENT_WATCHER_{safe_name}.json")
            w.load_state()
            self.watchers[name] = w
        return self.watchers[name]

    def _add_saipen_cmd(self, cmd: str) -> None:
        self.watcher_prompt_var.set(cmd)
        self.watcher_add_prompt()

    def _build_watcher_group(self, root: tk.Misc) -> None:
        group = self.group(root, " Watcher (очередь промптов) ")
        group.pack(fill="x", pady=(7, 0))

        if not hasattr(self, "watcher_adapter_var"):
            self.watcher_adapter_var = tk.StringVar(value="antigravity")
        self.current_watcher = self.get_watcher(self.watcher_adapter_var.get())

        adapter_row = vframe(group)
        adapter_row.pack(fill="x")

        vlabel(adapter_row, text="Агент:", small=True).pack(side="left")
        self.watcher_adapter_var = tk.StringVar(
            value=self.current_watcher.adapter_name or "— ручная проба —"
        )
        adapter_names = self.watcher_adapter_names()
        self.watcher_adapter_combo = ttk.Combobox(
            adapter_row,
            textvariable=self.watcher_adapter_var,
            values=adapter_names,
            state="normal",
            width=18,
            style="Vintage.TCombobox",
        )
        self.watcher_adapter_combo.pack(side="left", padx=(4, 8))
        vbutton(
            adapter_row,
            "Применить агента",
            self.watcher_apply_adapter,
        ).pack(side="left")
        vbutton(
            adapter_row,
            "Запустить",
            self.watcher_launch_agent,
            role="primary",
        ).pack(side="left", padx=(4, 0))
        vbutton(
            adapter_row,
            "Запустить",
            self.watcher_launch_agent,
            role="primary",
        ).pack(side="left", padx=(4, 0))
        vbutton(
            adapter_row,
            "Сканировать",
            self.watcher_scan_agents,
        ).pack(side="left", padx=(4, 0))
        self.watcher_adapter_status_var = tk.StringVar(value="")
        vlabel(
            adapter_row,
            textvariable=self.watcher_adapter_status_var,
            muted=True,
            small=True,
        ).pack(side="left", padx=(8, 0))
        self.watcher_glob_var = tk.StringVar()
        if self.current_watcher.probes:
            probe = self.current_watcher.probes[0]
            self.watcher_glob_var.set(
                getattr(probe, "pattern", "") or getattr(probe, "path", "")
            )
        vlabel(
            adapter_row,
            textvariable=self.watcher_glob_var,
            muted=True,
            small=True,
        ).pack(side="left", padx=(8, 0))

        probe_row = vframe(group)
        # probe_row.pack() hidden for intuition

        self.watcher_probe_kind_var = tk.StringVar(
            value=self.current_watcher.probes[0].kind if self.current_watcher.probes else "file"
        )
        ttk.Combobox(
            probe_row,
            textvariable=self.watcher_probe_kind_var,
            values=["file", "sqlite"],
            state="readonly",
            width=7,
            style="Vintage.TCombobox",
        ).pack(side="left")

        vlabel(probe_row, text="Glob/путь БД:", small=True).pack(
            side="left", padx=(4, 0)
        )
        self.watcher_glob_var = tk.StringVar()
        if self.current_watcher.probes:
            probe = self.current_watcher.probes[0]
            self.watcher_glob_var.set(
                getattr(probe, "pattern", "") or getattr(probe, "path", "")
            )
        ventry(probe_row, textvariable=self.watcher_glob_var, width=26).pack(
            side="left", padx=(4, 8)
        )

        vlabel(probe_row, text="Тихих, мс:", small=True).pack(side="left")
        self.watcher_quiet_var = tk.StringVar(
            value=str(self.current_watcher.probes[0].quiet_ms
                      if self.current_watcher.probes else 2000)
        )
        ventry(probe_row, textvariable=self.watcher_quiet_var, width=6).pack(
            side="left", padx=(4, 8)
        )
        vbutton(probe_row, "Применить", self.watcher_apply_probe).pack(
            side="left"
        )

        sqlite_row = vframe(group)
        # sqlite_row.pack() hidden for intuition
        vlabel(sqlite_row, text="Watch:", small=True).pack(side="left")
        self.watcher_watch_var = tk.StringVar(
            value=getattr(self.current_watcher.probes[0], "watch", "wal_mtime")
            if self.current_watcher.probes else "wal_mtime"
        )
        ttk.Combobox(
            sqlite_row,
            textvariable=self.watcher_watch_var,
            values=["wal_mtime", "max_rowid"],
            state="readonly",
            width=10,
            style="Vintage.TCombobox",
        ).pack(side="left")
        vlabel(sqlite_row, text="Таблица (max_rowid):", small=True).pack(
            side="left", padx=(4, 0)
        )
        self.watcher_table_var = tk.StringVar(
            value=getattr(self.current_watcher.probes[0], "table", "")
            if self.current_watcher.probes else ""
        )
        ventry(sqlite_row, textvariable=self.watcher_table_var, width=12).pack(
            side="left", padx=(4, 8)
        )
        vlabel(
            sqlite_row,
            text="только для sqlite",
            muted=True,
            small=True,
        ).pack(side="left")

        queue_row = vframe(group)
        queue_row.pack(fill="x", pady=(4, 0))

        self.watcher_queue_list = tk.Listbox(
            queue_row,
            height=4,
            font=FONT_SMALL,
            bg=C["compareBack"],
            fg=C["textPrimary"],
            selectbackground=C["selection"],
            selectforeground=C["textPrimary"],
            relief="sunken",
            bd=2,
            highlightthickness=0,
            activestyle="none",
        )
        self.watcher_queue_list.pack(side="left", fill="both", expand=True)
        self.watcher_refresh_queue()

        side = vframe(queue_row)
        side.pack(side="left", padx=(6, 0), fill="y")

        vlabel(side, text="Диалог (имя сессии):", small=True).pack(anchor="w")
        self.watcher_dialog_var = tk.StringVar()
        ventry(side, textvariable=self.watcher_dialog_var, width=24).pack(
            fill="x"
        )
        vlabel(side, text="Текст:", small=True).pack(anchor="w")
        self.watcher_prompt_var = tk.StringVar()
        ventry(side, textvariable=self.watcher_prompt_var, width=24).pack(
            fill="x"
        )
        row2 = vframe(side)
        row2.pack(fill="x", pady=(4, 0))
        vbutton(row2, "Добавить", self.watcher_add_prompt).pack(side="left")
        vbutton(
            row2,
            "Удалить",
            self.watcher_remove_prompt,
            role="danger",
        ).pack(side="left", padx=(4, 0))

        saipen_frame = vframe(side)
        saipen_frame.pack(fill="x", pady=(4, 0))
        cmds = ['cc', 'ccc', 'ss', 'sss', 'gg', 'hh', 'dd']
        for cmd in cmds:
            btn = tk.Button(saipen_frame, text=cmd, command=lambda c=cmd: self._add_saipen_cmd(c), 
                            font=("Verdana", 7), bg=C["surfaceRaised"], fg=C["textPrimary"], relief="raised", bd=1, padx=2, pady=0)
            btn.pack(side="left", padx=(0, 2))
            
        saipen_frame2 = vframe(side)
        saipen_frame2.pack(fill="x", pady=(2, 0))
        cmds2 = ['aa', 'qq', 'qqq', 'ee', 'eee', 'pp']
        for cmd in cmds2:
            btn = tk.Button(saipen_frame2, text=cmd, command=lambda c=cmd: self._add_saipen_cmd(c), 
                            font=("Verdana", 7), bg=C["surfaceRaised"], fg=C["textPrimary"], relief="raised", bd=1, padx=2, pady=0)
            btn.pack(side="left", padx=(0, 2))

        arm_row = vframe(group)
        arm_row.pack(fill="x", pady=(4, 0))

        self.watcher_arm_button = vbutton(
            arm_row,
            "ЗАПУСТИТЬ WATCHER",
            self.watcher_toggle,
            role="primary",
            width=20,
        )
        self.watcher_arm_button.pack(side="left")

        self.watcher_history_button = vbutton(
            arm_row,
            f"История ({len(self.current_watcher.send_log.entries)})",
            self.watcher_show_history,
            width=14,
        )
        self.watcher_history_button.pack(side="left", padx=(6, 0))

        self.watcher_status_var = tk.StringVar(value="Watcher выключен.")
        tk.Label(
            arm_row,
            textvariable=self.watcher_status_var,
            font=FONT_SMALL,
            bg=C["surfaceRaised"],
            fg=C["textSecondary"],
            anchor="w",
        ).pack(side="left", fill="x", expand=True, padx=(8, 0))

        limit_row = vframe(group)
        # limit_row.pack() hidden for intuition

        self.watcher_limit_var = tk.BooleanVar(
            value=self.current_watcher.limit_enabled
        )
        vcheck(
            limit_row,
            variable=self.watcher_limit_var,
            text="Соблюдать лимит агента: не слать при «limit reached», "
                 "отправить после сброса",
            command=self.watcher_limit_toggled,
        ).pack(side="left")

        self.watcher_limit_status_var = tk.StringVar(value="")
        tk.Label(
            limit_row,
            textvariable=self.watcher_limit_status_var,
            font=FONT_SMALL,
            bg=C["surfaceRaised"],
            fg=C["warning"],
            anchor="e",
        ).pack(side="right")

    # ---- watcher callbacks -------------------------------------------
    def watcher_thread_status(self, state: str, message: str) -> None:
        self.ui_queue.put(("watcher_status", state, message))

    def watcher_refresh_queue(self) -> None:
        if not hasattr(self, "watcher_queue_list"):
            return
        self.watcher_queue_list.delete(0, "end")
        for text in self.current_watcher.prompts():
            self.watcher_queue_list.insert("end", text)

    def watcher_limit_toggled(self) -> None:
        self.current_watcher.limit_enabled = bool(self.watcher_limit_var.get())
        if not self.current_watcher.limit_enabled:
            self.current_watcher._limit_until = None
            self.current_watcher._limit_reason = ""
            self.current_watcher._limit_resume_token = None
            self.current_watcher._limit_grace_until = None
        self.current_watcher.save_state()
        self.watcher_limit_status_var.set("")
        self.log(
            "Watcher лимит: "
            + ("включён" if self.current_watcher.limit_enabled else "выключен") + "."
        )

    # ---- watcher adapters --------------------------------------------
    def watcher_adapter_names(self) -> list[str]:
        names: list[str] = []
        try:
            adapters, _limits, _errors = load_adapters(
                ADAPTERS_PATH, fallback=None
            )
        except Exception:
            return names
        for adapter in adapters:
            names.append(adapter.name)
        return names

    def watcher_apply_adapter(self) -> None:
        if self.current_watcher.armed:
            self.set_status(
                "ERROR",
                "Останови watcher перед сменой агента: проба применится при запуске.",
            )
            return
        name = self.watcher_adapter_var.get().strip()
        if not name or name == "— ручная проба —":
            self.set_status("ERROR", "Выбери агента из списка.")
            return
        try:
            adapters, _limits, errors = load_adapters(
                ADAPTERS_PATH, fallback=None
            )
        except Exception as exc:
            self.set_status("ERROR", f"Адаптеры не прочитались: {exc}")
            return
        for error in errors:
            self.log(f"Watcher адаптеры: {error}")
        adapter = next((a for a in adapters if a.name == name), None)
        if adapter is None:
            self.set_status("ERROR", f"Агент {name!r} не найден в конфиге.")
            return
        ok, reason = adapter.supported()
        if not ok:
            self.watcher_adapter_status_var.set(reason)
            self.set_status("ERROR", f"Агент {name!r}: {reason}")
            return
        if not self.current_watcher.apply_adapter(adapter):
            self.set_status(
                "ERROR", "Останови watcher перед сменой агента."
            )
            return
        # Показываем, что применилось, в полях ручной пробы. Для
        # window/process-проб пути нет — поля очищаем, а не врём.
        probe = adapter.probes[0] if adapter.probes else None
        if probe is not None:
            self.watcher_probe_kind_var.set(probe.kind)
            self.watcher_quiet_var.set(str(probe.quiet_ms))
            if probe.kind == "file":
                self.watcher_glob_var.set(getattr(probe, "pattern", ""))
                self.watcher_watch_var.set("wal_mtime")
                self.watcher_table_var.set("")
            elif probe.kind == "sqlite":
                self.watcher_glob_var.set(getattr(probe, "path", ""))
                self.watcher_watch_var.set(getattr(probe, "watch", "wal_mtime"))
                self.watcher_table_var.set(getattr(probe, "table", ""))
            else:
                self.watcher_glob_var.set("")
                self.watcher_watch_var.set("wal_mtime")
                self.watcher_table_var.set("")
        transport = self.current_watcher.adapter_transport
        cdp_note = ""
        if transport == "cdp":
            port = adapter.live_cdp_port()
            cdp_note = f" · cdp-порт {port}" if port else " · cdp (порт не найден)"
        self.watcher_adapter_status_var.set(
            f"settle {adapter.settle_ms} мс · доставка Win32 · "
            f"конфиг: {transport}{cdp_note}"
        )
        self.log(
            f"Watcher агент: {name} (конфиг-транспорт {transport}, "
            f"settle {adapter.settle_ms} мс, доставка Win32)."
        )
        self.set_status("SAVED", f"Агент {name} применён.")

    def watcher_scan_agents(self) -> None:
        """Find installed CLI agents and append missing blocks to
        SAISENT_ADAPTERS.toml. Never overwrites what's already there."""
        try:
            found = scan_installed_agents()
        except Exception as exc:
            self.set_status("ERROR", f"Сканирование не удалось: {exc}")
            self.log(f"Watcher сканер: {exc}")
            return
        if not found:
            self.watcher_adapter_status_var.set("ничего не найдено")
            self.set_status("IDLE", "Сканер не нашёл установленных агентов.")
            return

        try:
            adapters, _limits, _errors = load_adapters(
                ADAPTERS_PATH, fallback=None
            )
        except Exception:
            adapters = []
        existing = {a.name for a in adapters}
        fresh = [block for block in found if block["name"] not in existing]
        if not fresh:
            self.watcher_adapter_status_var.set(
                "все найденные агенты уже в конфиге"
            )
            self.set_status("IDLE", "Сканер: новые агенты не нужны.")
            return

        try:
            text = "\n\n" + "\n\n".join(
                _toml_block(block) for block in fresh
            ) + "\n"
            with open(ADAPTERS_PATH, "a", encoding="utf-8") as fh:
                fh.write(text)
        except OSError as exc:
            self.set_status("ERROR", f"Не удалось дописать конфиг: {exc}")
            return

        names = ", ".join(block["name"] for block in fresh)
        self.watcher_adapter_status_var.set(f"добавлено: {names}")
        # Обновляем комбобокс, чтобы новый агент был виден сразу.
        try:
            if hasattr(self, "watcher_adapter_combo"):
                self.watcher_adapter_combo.configure(
                    values=self.watcher_adapter_names()
                )
            self.watcher_adapter_var.set(fresh[0]["name"])
        except Exception:
            pass
        self.log(f"Watcher сканер: добавлены агенты {names} в "
                 f"{ADAPTERS_PATH.name}.")
        self.set_status("SAVED", f"Сканер добавил: {names}")

    def watcher_apply_probe(self) -> None:
        if self.current_watcher.armed:
            self.set_status(
                "ERROR",
                "Останови watcher перед сменой пробы: она применится при запуске.",
            )
            return
        try:
            quiet = int(self.watcher_quiet_var.get().strip())
            quiet = max(0, min(quiet, 60000))
        except (TypeError, ValueError):
            quiet = 2000
        kind = self.watcher_probe_kind_var.get().strip().lower() or "file"
        path = self.watcher_glob_var.get().strip()
        watch = self.watcher_watch_var.get().strip() or "wal_mtime"
        table = self.watcher_table_var.get().strip()
        self.current_watcher.set_probe(kind, path, quiet, watch=watch, table=table)
        if self.current_watcher.save_state():
            self.log(f"Watcher проба: {kind} {path!r}, "
                     f"watch={watch}, table={table!r}, quiet={quiet} мс.")
            self.set_status("SAVED", "Проба watcher сохранена.")

    def watcher_add_prompt(self) -> None:
        text = self.watcher_prompt_var.get()
        dialog = self.watcher_dialog_var.get()
        if self.current_watcher.add_prompt(text, dialog=dialog):
            self.watcher_prompt_var.set("")
            if dialog:
                self.watcher_dialog_var.set("")
            self.watcher_refresh_queue()
            if dialog:
                self.log(f"Watcher: добавлен промпт {text!r} в диалог {dialog!r}.")
            else:
                self.log(f"Watcher: добавлен промпт {text!r}.")
        else:
            self.set_status("ERROR", "Промпт пустой.")

    def watcher_remove_prompt(self) -> None:
        selection = self.watcher_queue_list.curselection()
        if not selection:
            return
        index = int(selection[0])
        if self.current_watcher.remove_prompt(index):
            self.watcher_refresh_queue()
            self.log("Watcher: промпт удалён.")

    def watcher_toggle(self) -> None:
        if self.current_watcher.armed:
            self.current_watcher.disarm()
            self.watcher_arm_button.configure(text="ЗАПУСТИТЬ WATCHER")
            style_button(self.watcher_arm_button, "primary")
            self.watcher_status_var.set("Watcher выключен.")
            return

        # Перед запуском привязываем цель к текущему конфигу окна.
        self.current_watcher.target.exe_name = self.config.exe_name
        self.current_watcher.target.class_name = self.config.class_name
        self.current_watcher.target.title_contains = self.config.title_contains
        self.current_watcher.save_state()

        ok, message = self.current_watcher.arm()
        if ok:
            self.watcher_arm_button.configure(text="ОСТАНОВИТЬ WATCHER")
            style_button(self.watcher_arm_button, "danger")
            self.watcher_status_var.set("Watcher запущен.")
        else:
            self.set_status("ERROR", message)
            self.log(f"Watcher не запущен: {message}")

    def watcher_show_history(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title(f"{APP_NAME} — История отправок")
        dialog.configure(bg=C["surfaceRaised"])
        dialog.geometry("620x360")
        dialog.transient(self)

        header = vframe(dialog)
        header.pack(fill="x", padx=6, pady=(6, 2))
        vlabel(
            header,
            text="Что реально ушло в агента (время · OK/FAIL · текст):",
            small=True,
        ).pack(side="left")
        vbutton(
            header,
            "Очистить",
            lambda: self.watcher_clear_history(dialog),
            role="danger",
            width=10,
        ).pack(side="right")

        # График отправок по часам за последние 24 ч.
        chart = tk.Canvas(
            dialog,
            height=90,
            bg=C["compareBack"],
            highlightthickness=1,
            highlightbackground=C["borderMuted"],
            bd=0,
        )
        chart.pack(fill="x", padx=6, pady=(0, 4))
        self._draw_send_chart(chart)

        frame = vframe(dialog)
        frame.pack(fill="both", expand=True, padx=6, pady=2)

        self.history_list = tk.Listbox(
            frame,
            height=14,
            font=("Consolas", 9),
            bg=C["compareBack"],
            fg=C["textPrimary"],
            selectbackground=C["selection"],
            selectforeground=C["textPrimary"],
            relief="sunken",
            bd=2,
            highlightthickness=0,
            activestyle="none",
        )
        self.history_list.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(
            frame,
            orient="vertical",
            command=self.history_list.yview,
            style="Vintage.Vertical.TScrollbar",
        )
        scrollbar.pack(side="right", fill="y")
        self.history_list.configure(yscrollcommand=scrollbar.set)

        for entry in self.current_watcher.send_history(300):
            at = entry.get("at", "")[11:19]
            state = (
                "OK  "
                if entry.get("ok")
                else ("DRY " if entry.get("dry") else "FAIL")
            )
            text = (entry.get("text") or "").replace("\n", " ")
            if len(text) > 72:
                text = text[:72] + "…"
            reason = entry.get("reason") or ""
            target = entry.get("target") or ""
            line = f"{at}  {state}  {text}"
            if reason and not entry.get("ok"):
                line += f"  [{reason}]"
            if target:
                line += f"  → {target}"
            self.history_list.insert("end", line)

        bottom = vframe(dialog)
        bottom.pack(fill="x", padx=6, pady=(2, 6))
        vbutton(bottom, "Закрыть", dialog.destroy, width=10).pack(side="right")
        dialog.grab_set()

    def _draw_send_chart(self, chart: tk.Canvas) -> None:
        """Бары отправок по часам за последние 24 часа: OK — зелёный,
        FAIL/DRY — красный. Сверху — итог за сутки."""
        entries = self.current_watcher.send_history(10000)
        buckets: dict[int, list[int]] = {}   # hour -> [ok, fail]
        for entry in entries:
            at = entry.get("at", "")
            try:
                hour = int(at[11:13])
            except (ValueError, TypeError):
                continue
            pair = buckets.setdefault(hour, [0, 0])
            if entry.get("ok"):
                pair[0] += 1
            else:
                pair[1] += 1

        total_ok = sum(p[0] for p in buckets.values())
        total_fail = sum(p[1] for p in buckets.values())
        chart.delete("all")
        # До первого маппинга окна winfo_width()==1 — рисуем с гарантированным
        # размером, иначе бары уходят за границу холста.
        width = max(int(chart.winfo_width()), 620)
        height = max(int(chart.winfo_height()), 90)

        chart.create_text(
            6, 4, anchor="nw", fill=C["textSecondary"],
            font=("Verdana", 8),
            text=f"За сутки: OK {total_ok} · FAIL {total_fail}",
        )

        if not buckets:
            chart.create_text(
                width // 2, height // 2, fill=C["textMuted"],
                font=("Verdana", 9), text="Нет отправок за сутки",
            )
            return

        max_total = max(sum(p) for p in buckets.values()) or 1
        bar_w = max(6, min(16, (width - 70) // 24))
        chart_height = height - 26
        baseline = height - 8

        for hour in range(24):
            ok, fail = buckets.get(hour, (0, 0))
            if ok + fail == 0:
                continue
            x = 40 + hour * (bar_w + 4)
            total = ok + fail
            y_top = baseline - chart_height * total / max_total
            chart.create_rectangle(
                x, baseline, x + bar_w, y_top,
                fill=C["success"], outline=C["success"],
            )
            if fail:
                fail_frac = fail / total
                chart.create_rectangle(
                    x, baseline, x + bar_w,
                    y_top + chart_height * fail_frac * total / max_total,
                    fill=C["danger"], outline=C["danger"],
                )
            if hour % 3 == 0:
                chart.create_text(
                    x + bar_w // 2, height - 4, anchor="n",
                    fill=C["textMuted"], font=("Verdana", 7), text=f"{hour}",
                )

    def watcher_clear_history(self, dialog: tk.Toplevel) -> None:
        self.current_watcher.clear_send_log()
        self.history_list.delete(0, "end")
        self.watcher_history_button.configure(
            text="История (0)"
        )
        self.log("Watcher: история отправок очищена.")
        dialog.grab_release()

    def set_watcher_status(self, state: str, message: str) -> None:
        self.watcher_status_var.set(f"[{state}] {message}")
        if hasattr(self, "watcher_history_button"):
            self.watcher_history_button.configure(
                text=f"История ({len(self.current_watcher.send_log.entries)})"
            )
        if self.current_watcher.limit_enabled and self.current_watcher._limit_until is not None:
            self.watcher_limit_status_var.set(
                self.current_watcher._limit_reason
            )
        else:
            self.watcher_limit_status_var.set("")
        armed = self.current_watcher.armed
        label = "ОСТАНОВИТЬ WATCHER" if armed else "ЗАПУСТИТЬ WATCHER"
        if self.watcher_arm_button.cget("text") != label:
            self.watcher_arm_button.configure(text=label)
            style_button(
                self.watcher_arm_button,
                "danger" if armed else "primary",
            )


    def watcher_launch_agent(self) -> None:
        if not self.current_watcher.adapter:
            return
        name = self.current_watcher.adapter.name
        cmd = "claude" if "claude" in name.lower() else name.lower().replace(" ", "")
        title = f"[SAISENT] {name}"
        
        import subprocess
        subprocess.Popen(f'start "{title}" cmd.exe /c "{cmd}"', shell=True)
        
        def bind_target():
            wins = find_windows(title_contains=title, api=self.api)
            if wins:
                self.current_watcher.target.hwnd = wins[0].hwnd
                self.current_watcher.target.title_contains = title
                self.ui_queue.put(("watcher_status", name, self.current_watcher.armed, self.current_watcher.sent_count, 0, f"Терминал {title} привязан!"))
        self.after(1500, bind_target)

    def _build_chat_viewer(self, root: tk.Misc) -> None:
        group = self.group(root, " Live Chat Viewer ")
        group.pack(fill="both", expand=True, pady=(7, 0))
        
        self.chat_text = tk.Text(
            group,
            height=10,
            font=("Verdana", 9),
            bg=C["compareBack"],
            fg=C["textPrimary"],
            relief="sunken",
            bd=2,
            highlightthickness=0,
            state="disabled",
            wrap="word"
        )
        self.chat_text.pack(fill="both", expand=True, padx=4, pady=4)
        self.chat_last_file = ""
        self.chat_last_size = 0

    def update_chat_viewer(self) -> None:
        self.after(1000, self.update_chat_viewer)
        if getattr(self, "closing", False) or not self.current_watcher.probes:
            return
            
        probe = self.current_watcher.probes[0]
        if probe.kind != "file":
            return
            
        try:
            import os
            path = getattr(probe, "path", None) or getattr(probe, "pattern", None)
            if not path:
                try:
                    path = probe._path()
                except Exception:
                    pass
            if not path or not os.path.exists(path):
                return
                
            size = os.path.getsize(path)
            if path != self.chat_last_file:
                self.chat_last_file = path
                self.chat_last_size = 0
                self.chat_text.config(state="normal")
                self.chat_text.delete(1.0, tk.END)
                self.chat_text.insert(tk.END, f"--- Читаю лог: {os.path.basename(path)} ---\n\n")
                self.chat_text.config(state="disabled")
                
            if size > self.chat_last_size:
                import json
                with open(path, "r", encoding="utf-8") as f:
                    f.seek(self.chat_last_size)
                    new_data = f.read()
                    
                self.chat_last_size = size
                
                self.chat_text.config(state="normal")
                for line in new_data.splitlines():
                    line = line.strip()
                    if not line: continue
                    try:
                        data = json.loads(line)
                        if "type" in data:
                            msg_type = data["type"]
                            text = ""
                            if msg_type == "assistant":
                                text = "🤖 " + data.get("message", "")
                            elif msg_type == "user":
                                text = "👤 " + data.get("message", "")
                            
                            if text:
                                self.chat_text.insert(tk.END, text + "\n\n")
                                self.chat_text.see(tk.END)
                    except Exception:
                        pass
                self.chat_text.config(state="disabled")
        except Exception:
            pass

    def _build_bottom(self, root: tk.Misc) -> None:
        bottom = tk.Frame(
            root,
            bg=C["surfaceRaised"],
            relief="groove",
            bd=2,
        )
        bottom.pack(fill="x", pady=(7, 0))

        actions = vframe(bottom)
        actions.pack(fill="x", padx=4, pady=4)

        self.tray_row = vframe(bottom)
        self.tray_row.pack(fill="x", padx=4, pady=(0, 0))

        self.tray_var = tk.BooleanVar(value=self.config.tray_enabled)
        vcheck(
            self.tray_row,
            variable=self.tray_var,
            text="Сворачивать в трей при закрытии (watcher и расписание продолжают)",
            command=self.mark_dirty,
        ).pack(side="left")

        self.save_button = vbutton(
            actions,
            "Сохранить",
            self.save,
            width=10,
        )
        self.save_button.pack(side="left")

        vbutton(
            actions,
            "Журнал",
            self.open_log,
            width=8,
        ).pack(side="left", padx=(4, 0))

        self.stop_button = vbutton(
            actions,
            "СТОП",
            self.stop_run,
            role="danger",
            width=7,
            state="disabled",
        )
        self.stop_button.pack(side="right")

        status_row = vframe(bottom)
        status_row.pack(fill="x", padx=4, pady=(0, 4))

        self.status_state_var = tk.StringVar(value="IDLE")
        self.status_message_var = tk.StringVar(value="Готово.")

        self.status_state_label = tk.Label(
            status_row,
            textvariable=self.status_state_var,
            font=FONT_SMALL,
            bg=C["surfaceRaised"],
            fg=C["textSecondary"],
            width=9,
            anchor="w",
        )
        self.status_state_label.pack(side="left")

        self.status_message_label = tk.Label(
            status_row,
            textvariable=self.status_message_var,
            font=FONT_SMALL,
            bg=C["compareBack"],
            fg=C["textPrimary"],
            relief="sunken",
            bd=2,
            anchor="w",
            padx=4,
        )
        self.status_message_label.pack(side="left", fill="x", expand=True)

    def load_config(self) -> tuple[AppConfig, bool, str]:
        if not CONFIG_PATH.exists():
            return AppConfig(), False, ""

        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("Корень JSON должен быть объектом.")
            config, migrated = AppConfig.from_dict(raw)
            return config, migrated, ""
        except Exception as exc:
            return (
                AppConfig(),
                False,
                f"Не удалось прочитать {CONFIG_PATH.name}; загружены defaults. {exc}",
            )

    def update_summaries(self) -> None:
        title = self.config.title_contains.strip() or "любой заголовок"
        exe = self.config.exe_name.strip() or "любой exe"
        self.target_summary_var.set(f"{title}  |  {exe}")
        self.refresh_arm_state()
        self.update_countdown()

    def refresh_arm_state(self) -> None:
        if self.saved_config.schedule_enabled:
            self.arm_button.configure(text="ОТМЕНИТЬ РАСПИСАНИЕ")
            style_button(self.arm_button, "danger")
        else:
            self.arm_button.configure(text="ЗАПУСТИТЬ ПО РАСПИСАНИЮ")
            style_button(self.arm_button, "primary")

    def mark_dirty(self) -> None:
        if not self.dirty:
            self.set_dirty(True)

    def set_dirty(self, value: bool) -> None:
        self.dirty = value
        suffix = " *" if value else ""
        self.title(f"{APP_NAME} {APP_VERSION}{suffix}")

    def set_status(self, state: str, message: str) -> None:
        self.status_state_var.set(state)
        self.status_message_var.set(message)
        self.status_state_label.configure(
            fg=self.STATUS_COLORS.get(state, C["textSecondary"])
        )

        running = state == "RUNNING"
        self.run_now_button.configure(state="disabled" if running else "normal")
        self.stop_button.configure(state="normal" if running else "disabled")

        if hasattr(self, "tray") and self.tray._visible:
            self.tray.set_status(self._tray_status())

        if state == "ERROR":
            self.bell()

    def thread_status(self, state: str, message: str) -> None:
        self.ui_queue.put(("status", state, message))

    def thread_log(self, message: str) -> None:
        self.ui_queue.put(("log", message))

    def thread_completed(self, success: bool, state: str = "DONE") -> None:
        self.ui_queue.put(("run_done", success, state))

    def hotkey_action(self, action: str) -> None:
        self.ui_queue.put(("hotkey", action))

    def process_ui_queue(self) -> None:
        try:
            while True:
                item = self.ui_queue.get_nowait()
                kind = item[0]
                try:
                    if kind == "status":
                        self.set_status(item[1], item[2])
                    elif kind == "log":
                        self.log(item[1])
                    elif kind == "watcher_status":
                        self.set_watcher_status(str(item[1]), str(item[2]))
                    elif kind == "run_done":
                        success = bool(item[1])
                        state = str(item[2]) if len(item) > 2 else "DONE"
                        self.on_run_done(success, state)
                    elif kind == "hotkey":
                        action = item[1]
                        if action == "run":
                            self.run_now(reason="hotkey")
                        elif action == "stop":
                            self.stop_run()
                        elif action == "show":
                            self.show_window()
                    elif kind == "tray_restore":
                        self._show_from_tray()
                    elif kind == "tray_quit":
                        self._force_quit = True
                        self.on_close()
                except Exception as exc:
                    self.log(f"Ошибка обработки события UI: {exc}")

        except queue.Empty:
            pass

        if not self.closing:
            self.after(500, self.process_ui_queue)

    def on_run_done(self, success: bool, state: str = "DONE") -> None:
        cfg = self.saved_config
        if not (cfg.schedule_enabled and cfg.repeat_enabled):
            return
        if self.closing:
            return

        base = self._scheduled_fire_base
        self._scheduled_fire_base = None

        # Отложенное срабатывание: в момент расписания runner был занят
        # (ручной запуск). Выполняем пропущенный запуск сразу же.
        if self._pending_fire:
            if self._limit_gate_active():
                # Лимит агента снова активен: пропущенное срабатывание ждёт,
                # цепочку не двигаем — следующий тик запустит после сброса.
                self.log(
                    "Пропущенное срабатывание отложено: лимит агента активен."
                )
                return
            self._pending_fire = False
            if self.runner.start(cfg, "schedule"):
                self._scheduled_fire_base = datetime.now()
                nxt = self._shift_next_run(cfg, datetime.now())
                self.log(
                    "Пропущенное срабатывание выполнено. "
                    f"Следующая попытка: {nxt.strftime('%d.%m %H:%M:%S')}."
                )
                self.update_summaries()
            return

        if not success and state == "ERROR":
            # Сбой (окно не найдено, потерян фокус и т.п.): повторить вскоре,
            # а не ждать полный интервал.
            nxt = datetime.now() + timedelta(minutes=REPEAT_RETRY_MINUTES)
            cfg.next_run = nxt.isoformat(timespec="seconds")
            self.config.next_run = cfg.next_run
            self._write_schedule_date()
            self.log(
                "Не удалось. Повтор через "
                f"{REPEAT_RETRY_MINUTES} мин: "
                f"{nxt.strftime('%d.%m %H:%M:%S')}."
            )
            self.update_summaries()
            return

        # Успех или остановка: при плановом срабатывании цепочка уже сдвинута
        # в момент запуска (_repeat_tick). Ручной запуск (base is None) —
        # сдвигаем от текущего момента.
        if base is None:
            nxt = self._shift_next_run(cfg, datetime.now())
        else:
            nxt = parse_iso_time(cfg.next_run)
            if nxt is None:
                nxt = self._shift_next_run(cfg, base)

        verdict = "Успешно" if success else "Остановлено"
        self.log(
            f"{verdict}. Следующая попытка автоповтора: "
            f"{nxt.strftime('%d.%m %H:%M:%S')}."
        )
        self.update_summaries()

    def refresh_preset_ops(self) -> None:
        names = list(load_presets().keys())
        self.editor.set_presets(names)

    def preset_save(self) -> None:
        name = self.editor.preset_var.get().strip()
        if not name:
            messagebox.showwarning(
                APP_NAME,
                "Впиши имя в поле пресета и нажми «Сохр.».",
                parent=self,
            )
            return

        steps = copy.deepcopy(self.editor.steps)
        if not steps:
            messagebox.showwarning(
                APP_NAME,
                "Нечего сохранять: добавь хотя бы одно действие.",
                parent=self,
            )
            return

        presets = load_presets()
        presets[name] = steps
        if not save_presets(presets):
            self.set_status("ERROR", f"Не удалось записать {PRESETS_PATH.name}.")
            return

        self.refresh_preset_ops()
        self.editor.preset_var.set(name)
        self.log(f"Пресет сохранён: {name!r} ({len(steps)} шагов).")
        self.set_status("SAVED", f"Пресет сохранён: {name}")

    def preset_load(self) -> None:
        name = self.editor.preset_var.get().strip()
        if not name:
            messagebox.showwarning(
                APP_NAME,
                "Выбери или впиши имя пресета.",
                parent=self,
            )
            return

        presets = load_presets()
        if name not in presets:
            messagebox.showerror(
                APP_NAME,
                f"Пресет {name!r} не найден.",
                parent=self,
            )
            return

        steps = copy.deepcopy(presets[name])
        self.editor.load_steps(steps)
        self.config.steps = steps
        self.mark_dirty()
        self.set_status("IDLE", f"Пресет загружен: {name}")
        self.log(f"Пресет загружен: {name!r} ({len(steps)} шагов).")

    def preset_delete(self) -> None:
        name = self.editor.preset_var.get().strip()
        if not name:
            return

        presets = load_presets()
        if name not in presets:
            return

        if not messagebox.askyesno(
            APP_NAME,
            f"Удалить пресет {name!r}?",
            parent=self,
        ):
            return

        del presets[name]
        save_presets(presets)
        self.refresh_preset_ops()
        self.editor.preset_var.set("")
        self.log(f"Пресет удалён: {name!r}")

    def log(self, message: str) -> None:
        line = f"{datetime.now().isoformat(timespec='seconds')} {message}\n"
        try:
            with LOG_PATH.open("a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError:
            pass

    def pick_window(self) -> None:
        WindowPicker(self, self.api)

    def set_target(self, info: WindowInfo) -> None:
        self.config.exe_name = info.exe_name
        self.config.class_name = info.class_name
        self.config.title_contains = info.title
        self.update_summaries()
        self.mark_dirty()
        self.set_status("IDLE", f"Выбрано: {info.title}")
        self.log(
            f"Выбрано окно: {info.title!r}, "
            f"{info.exe_name}, {info.class_name}, hwnd={info.hwnd}."
        )

    def test_activation(self) -> None:
        try:
            target = self.api.resolve_target(
                self.config.exe_name,
                self.config.class_name,
                self.config.title_contains,
            )

            if not self.api.activate_window(
                target.hwnd,
                self.config.activation_timeout_ms,
            ):
                raise RuntimeError(
                    "Окно найдено, но Windows не разрешила его активировать."
                )

            self.set_status("DONE", f"Активация работает: {target.title}")
            self.log(f"Активация OK: {target.title!r}, hwnd={target.hwnd}.")

        except Exception as exc:
            self.set_status("ERROR", str(exc))
            messagebox.showerror(APP_NAME, str(exc), parent=self)

    def capture_hotkey(self, variable: tk.StringVar) -> None:
        KeyCaptureDialog(
            self,
            self.api,
            variable.get(),
            variable.set,
            title="Записать hotkey",
        )

    def open_log(self) -> None:
        LogDialog(self)

    def _normalize_schedule_time(self, raw: str) -> str:
        seconds = parse_schedule_time(raw)
        hour, rem = divmod(seconds, 3600)
        minute, second = divmod(rem, 60)
        if second == 0:
            return f"{hour:02d}:{minute:02d}"
        return f"{hour:02d}:{minute:02d}:{second:02d}"

    def _sync_form_to_config(self) -> None:
        cfg = self.config
        cfg.schedule_time = self.schedule_time_var.get().strip()
        try:
            cfg.schedule_time = self._normalize_schedule_time(cfg.schedule_time)
        except ValueError:
            pass
        cfg.run_if_missed = bool(self.missed_var.get())
        cfg.repeat_enabled = bool(self.repeat_var.get())
        try:
            cfg.interval_hours = int(self.interval_var.get().strip())
        except (TypeError, ValueError):
            raise ValueError("Интервал автоповтора должен быть целым числом.")
        cfg.hotkeys_enabled = bool(self.hotkeys_enabled_var.get())
        cfg.hotkey_run = self.hotkey_run_var.get().strip()
        cfg.hotkey_stop = self.hotkey_stop_var.get().strip()
        cfg.hotkey_show = self.hotkey_show_var.get().strip()
        cfg.tray_enabled = bool(self.tray_var.get())
        try:
            cfg.activation_timeout_ms = int(self.timeout_var.get().strip())
            cfg.key_delay_ms = int(self.key_delay_var.get().strip())
        except (TypeError, ValueError):
            raise ValueError(
                "Таймаут активации и задержка клавиши должны быть целыми числами."
            )

    def toggle_schedule(self) -> None:
        was_enabled = self.saved_config.schedule_enabled
        try:
            if was_enabled:
                self.config.schedule_enabled = False
                self._pending_fire = False
                if self.save():
                    self.set_status("IDLE", "Расписание отключено.")
                else:
                    self.config.schedule_enabled = True
                return

            self._sync_form_to_config()
            cfg = self.config
            cfg.schedule_time = self._normalize_schedule_time(cfg.schedule_time)
            now = datetime.now()
            now_seconds = now.hour * 3600 + now.minute * 60 + now.second
            if parse_schedule_time(cfg.schedule_time) <= now_seconds:
                cfg.last_schedule_date = now.strftime("%Y-%m-%d")

            if cfg.repeat_enabled:
                slot = self._today_slot(now, cfg.schedule_time)
                if now < slot:
                    nxt = slot
                elif cfg.run_if_missed:
                    nxt = now
                else:
                    nxt = slot + timedelta(days=1)
                cfg.next_run = nxt.isoformat(timespec="seconds")
            else:
                cfg.next_run = ""

            cfg.schedule_enabled = True
            if self.save():
                message = f"Расписание установлено: {cfg.schedule_time}."
                if cfg.repeat_enabled:
                    message += f" Далее каждые {cfg.interval_hours} ч."
                self.set_status("SAVED", message)
        except Exception as exc:
            self.config.schedule_enabled = was_enabled
            self.set_status("ERROR", str(exc))
            messagebox.showerror(APP_NAME, str(exc), parent=self)

    def _apply_tray(self) -> None:
        enabled = bool(self.config.tray_enabled)
        if enabled and not self.tray._visible:
            self.tray.start(self._tray_status())
        elif not enabled and self.tray._visible:
            self.tray.stop()

    def _tray_status(self) -> str:
        try:
            state = self.status_state_var.get()
            message = self.status_message_var.get()
            return f"SAISENT [{state}] {message}"
        except Exception:
            return "SAISENT"

    def _tray_restore(self) -> None:
        # WNDPROC живёт на pump-потоке: в Tk-поток возвращаемся через очередь.
        self.ui_queue.put(("tray_restore",))

    def _show_from_tray(self) -> None:
        if not self.closing:
            self.deiconify()
            self.lift()
            self.focus_force()

    def _tray_quit(self) -> None:
        self.ui_queue.put(("tray_quit",))

    def save(self) -> bool:
        try:
            self._sync_form_to_config()
            validate_config(self.config, self.api)
            self.editor.refresh()
            atomic_write_json(CONFIG_PATH, self.config.to_dict())
            self.saved_config = copy.deepcopy(self.config)
            self.hotkeys.start(self.saved_config)
            self._apply_tray()
            self.set_dirty(False)
            self.set_status("SAVED", f"Сохранено: {CONFIG_PATH.name}")
            self.log(f"Настройки сохранены в {CONFIG_PATH.name}.")
            self.update_summaries()
            return True

        except Exception as exc:
            self.set_status("ERROR", str(exc))
            messagebox.showerror(APP_NAME, str(exc), parent=self)
            return False

    def run_now(self, reason: str = "manual") -> None:
        try:
            self._sync_form_to_config()
            snapshot = copy.deepcopy(self.config)
            validate_config(snapshot, self.api)

            if not self.runner.start(snapshot, reason):
                self.set_status("RUNNING", "Последовательность уже выполняется.")

        except Exception as exc:
            self.set_status("ERROR", str(exc))
            messagebox.showerror(APP_NAME, str(exc), parent=self)

    def stop_run(self) -> None:
        self.runner.stop()

    def show_window(self) -> None:
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after(50, lambda: self.attributes("-topmost", False))
        self.focus_force()

    def update_countdown(self) -> None:
        if not hasattr(self, "countdown_var"):
            return
        config = self.saved_config
        if not config.schedule_enabled:
            self.countdown_var.set("Расписание выключено.")
            return

        next_run = (
            parse_iso_time(config.next_run)
            if config.repeat_enabled
            else None
        )
        if next_run is not None:
            delta = int(max(0, (next_run - datetime.now()).total_seconds()))
            hour, rem = divmod(delta, 3600)
            minute, second = divmod(rem, 60)
            self.countdown_var.set(
                f"Автоповтор: {next_run.strftime('%H:%M:%S')} · "
                f"через {hour:02d}:{minute:02d}:{second:02d}"
            )
            return

        try:
            target_seconds = parse_schedule_time(config.schedule_time)
            now = datetime.now()
            now_seconds = now.hour * 3600 + now.minute * 60 + now.second
            delta = target_seconds - now_seconds
            if delta <= 0:
                delta += 86400
            hour, rem = divmod(delta, 3600)
            minute, second = divmod(rem, 60)
            self.countdown_var.set(
                f"Запуск: {config.schedule_time} · "
                f"через {hour:02d}:{minute:02d}:{second:02d}"
            )
        except ValueError:
            self.countdown_var.set("Время запуска: введите HH:MM[:SS].")

    def _write_schedule_date(self) -> None:
        try:
            atomic_write_json(CONFIG_PATH, self.saved_config.to_dict())
        except OSError as exc:
            self.log(f"Не удалось записать дату schedule: {exc}")

    def scheduler_tick(self) -> None:
        if self.closing:
            return

        try:
            config = self.saved_config
            now = datetime.now()

            if config.schedule_enabled:
                if config.repeat_enabled:
                    self._repeat_tick(config, now)
                else:
                    self._daily_tick(config, now)
        except Exception as exc:
            self.log(f"Ошибка расписания: {exc}")
        finally:
            # Цикл никогда не должен умереть: перезапуск гарантирован даже
            # при неожиданном исключении выше.
            self.first_tick = False
            try:
                self.update_countdown()
            except Exception:
                pass
            if not self.closing:
                self.after(500, self.scheduler_tick)

    @staticmethod
    def _today_slot(now: datetime, schedule_time: str) -> datetime:
        seconds = parse_schedule_time(schedule_time)
        return now.replace(
            hour=seconds // 3600,
            minute=(seconds % 3600) // 60,
            second=seconds % 60,
            microsecond=0,
        )

    def _limit_gate_active(self) -> bool:
        """Уважает ли планировщик лимит агента прямо сейчас.

        Положительный ответ только когда лимит-гейт реально вычислен и
        держит отправку. Если watcher не запущен и стор недоступен —
        возвращает False, и расписание идёт как обычно.
        """
        watcher = getattr(self, "watcher", None)
        if watcher is None:
            return False
        try:
            return watcher.limit_active()
        except Exception:
            return False

    def _derive_first_next_run(self, config: AppConfig, now: datetime) -> datetime:
        slot = self._today_slot(now, config.schedule_time)
        if now < slot:
            return slot
        if config.run_if_missed:
            return now
        return slot + timedelta(days=1)

    def _shift_next_run(self, config: AppConfig, base: datetime) -> datetime:
        """Advance next_run by the configured interval and persist it
        immediately. Returns the new datetime."""
        try:
            interval = max(1, int(config.interval_hours))
        except (TypeError, ValueError):
            interval = 5

        nxt = base + timedelta(hours=interval)
        config.next_run = nxt.isoformat(timespec="seconds")
        self.config.next_run = config.next_run
        self._write_schedule_date()
        return nxt

    def _repeat_tick(self, config: AppConfig, now: datetime) -> None:
        next_run = parse_iso_time(config.next_run)
        if next_run is None:
            next_run = self._derive_first_next_run(config, now)
            config.next_run = next_run.isoformat(timespec="seconds")
            self.config.next_run = config.next_run
            self._write_schedule_date()

        if self.runner.running:
            # Запуск сейчас невозможен: запоминаем пропущенное срабатывание,
            # чтобы выполнить его сразу после завершения текущего запуска.
            if now >= next_run:
                self._pending_fire = True
            return

        if now >= next_run:
            # Лимит агента активен (watcher-гейт): пропускаем срабатывание и
            # НЕ двигаем цепочку — next_run остаётся в прошлом, и как только
            # окно лимита пройдёт, следующий тик запустит сам. Так расписание
            # не шлёт промпт в «limit reached» и не теряет запуск.
            if self._limit_gate_active():
                if not self._limit_gate_was_active:
                    self._limit_gate_was_active = True
                    self.log(
                        "Расписание пропущено: лимит агента активен. "
                        "Запуск произойдёт после сброса лимита."
                    )
                return
            self._limit_gate_was_active = False

            if self.runner.start(config, "schedule"):
                self._pending_fire = False
                # Цепочку сдвигаем СРАЗУ при срабатывании и пишем на диск:
                # следующий запуск назначен ещё до окончания текущего, поэтому
                # перезапуск/закрытие программы или сбой обработки завершения
                # не потеряет автоповтор.
                self._scheduled_fire_base = now
                nxt = self._shift_next_run(config, now)
                self.log(
                    f"Сработало по расписанию: {now.strftime('%H:%M:%S')}. "
                    f"Следующая попытка: {nxt.strftime('%d.%m %H:%M:%S')}."
                )
            else:
                self.log("Сработало, но последовательность уже выполнялась.")

    def _daily_tick(self, config: AppConfig, now: datetime) -> None:
        target_seconds = parse_schedule_time(config.schedule_time)
        now_seconds = now.hour * 3600 + now.minute * 60 + now.second
        today = now.strftime("%Y-%m-%d")

        if config.last_schedule_date != today:
            delta = now_seconds - target_seconds
            fire = False

            if 0 <= delta <= FIRE_GRACE_SECONDS:
                fire = True
            elif delta > FIRE_GRACE_SECONDS and config.run_if_missed:
                fire = delta <= CATCHUP_GRACE_SECONDS or self.first_tick

            if fire:
                # Лимит агента активен: не помечаем день выполненным и не
                # запускаем — тик повторит попытку после сброса лимита.
                if self._limit_gate_active():
                    if not self._limit_gate_was_active:
                        self._limit_gate_was_active = True
                        self.log(
                            "Дневное расписание пропущено: лимит агента "
                            "активен. Запуск после сброса лимита."
                        )
                    return
                self._limit_gate_was_active = False
                if self.runner.start(config, "schedule"):
                    self.saved_config.last_schedule_date = today
                    self.config.last_schedule_date = today
                    self._write_schedule_date()

    def on_close(self) -> None:
        # Трей-режим: закрытие крестиком сворачивает в трей, а не гасит
        # watcher и расписание. Полный выход — только из меню трея.
        if (
            self.config.tray_enabled
            and self.tray._visible
            and not getattr(self, "_force_quit", False)
        ):
            self.withdraw()
            self.tray.set_status(self._tray_status() + " — в трее")
            self.log("Свёрнут в трей; watcher и расписание продолжают.")
            return

        if self.runner.running:
            answer = messagebox.askyesno(
                APP_NAME,
                "Последовательность ещё выполняется.\n"
                "Остановить её и закрыть SAISENT?",
                parent=self,
            )
            if not answer:
                return

        if self.dirty:
            answer = messagebox.askyesnocancel(
                APP_NAME,
                "Сохранить изменения перед закрытием?",
                parent=self,
            )

            if answer is None:
                return
            if answer and not self.save():
                return

        self.closing = True
        try:
            self.runner.stop()
            self.hotkeys.shutdown()
            if hasattr(self, "watcher"):
                self.current_watcher.disarm()
            self.tray.stop()
        finally:
            self.destroy()


def set_dpi_awareness() -> None:
    if os.name != "nt":
        return

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def acquire_single_instance() -> int:
    if os.name != "nt":
        return 0

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [wt.LPVOID, wt.BOOL, wt.LPCWSTR]
    kernel32.CreateMutexW.restype = wt.HANDLE

    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())

    ERROR_ALREADY_EXISTS = 183
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        import subprocess
        import time
        current_pid = os.getpid()
        cmd = f'wmic process where "name=\'pythonw.exe\' and commandline like \'%SAISENT.pyw%\' and ProcessId!=\'{current_pid}\'" call terminate'
        subprocess.run(cmd, shell=True, creationflags=0x08000000)
        time.sleep(0.5)
        
        # Освобождаем старый хэндл (хоть он и не владеет мьютексом, но лишним не будет)
        kernel32.CloseHandle(handle)
        
        # Пробуем снова
        handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if not handle or ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            # Если старый инстанс почему-то выжил, тогда просто выходим, но без окошка,
            # либо падаем молча.
            sys.exit(0)

    return int(handle)


def main() -> None:
    if os.name != "nt":
        raise SystemExit("SAISENT работает только в Windows.")

    set_dpi_awareness()
    mutex_handle = acquire_single_instance()
    api = WindowsAPI()
    app = SAISENTApp(api)
    app.mainloop()

    # Keep the mutex alive until the GUI closes.
    _ = mutex_handle


if __name__ == "__main__":
    main()
