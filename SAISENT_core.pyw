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


