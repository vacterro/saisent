"""Delivery: right window, right tab, atomic paste, honest confirmation."""

from __future__ import annotations

import pytest

from SAISENT_sessions.deliver import DEFAULT_WINDOW_TARGETS, Deliverer
from SAISENT_sessions.discover import Session


class FakeInfo:
    hwnd = 4242


class FakeApi:
    """Records what a real WindowsAPI would have been asked to do."""

    def __init__(self, foreground=True, activates=True, resolve_error=None):
        self.calls: list[tuple] = []
        self.foreground = foreground
        self.activates = activates
        self.resolve_error = resolve_error
        self.foreground_answers: list[bool] = []

    def resolve_target(self, exe, cls, title):
        self.calls.append(("resolve", exe, cls, title))
        if self.resolve_error:
            raise RuntimeError(self.resolve_error)
        return FakeInfo()

    def activate_window(self, hwnd, timeout_ms):
        self.calls.append(("activate", hwnd, timeout_ms))
        return self.activates

    def is_foreground(self, hwnd):
        if self.foreground_answers:
            return self.foreground_answers.pop(0)
        return self.foreground

    def send_combo(self, expression, delay):
        self.calls.append(("combo", expression))

    def send_text(self, text, delay):
        self.calls.append(("text", text))


class FakeClipboard:
    """T-052: also remembers what the user had copied, so a test can pin
    the restore -- a send must hand the user's clipboard back."""

    def __init__(self, ok=True, user_copied=None):
        self.ok = ok
        self.value = None
        self.user_copied = user_copied

    def get(self):
        return self.user_copied

    def set(self, text):
        self.value = text
        return self.ok


def session(agent="claude-code", key="claude-code:aaa", name="saisent-1"):
    return Session(
        key=key,
        agent=agent,
        name=name,
        project=r"V:\proj",
        session_id="aaa",
        started=0.0,
        last_active=0.0,
    )


def build(api, clipboard=None, activity=None, **kwargs):
    kwargs.setdefault("sleep", lambda _s: None)
    return Deliverer(
        api,
        clipboard=clipboard or FakeClipboard(),
        activity=activity,
        **kwargs,
    )


def combos(api):
    return [call[1] for call in api.calls if call[0] == "combo"]


# ------------------------------------------------------------ the happy path
def test_delivery_switches_tab_then_pastes_then_submits():
    api = FakeApi()
    clipboard = FakeClipboard()
    result = build(api, clipboard, confirm_timeout=0).deliver(
        session(), "hello there", tab_index=3
    )

    assert result.ok is True
    assert combos(api) == ["CTRL+3", "CTRL+V", "ENTER"]
    assert clipboard.value == "hello there"
    assert api.calls[0] == ("resolve",) + DEFAULT_WINDOW_TARGETS["claude-code"]


def test_no_tab_index_means_no_tab_switch():
    api = FakeApi()
    build(api, confirm_timeout=0).deliver(session(), "hi", tab_index=None)
    assert combos(api) == ["CTRL+V", "ENTER"]


def test_clipboard_guard_restores_the_users_copy():
    """T-052: a paste replaces the clipboard, so the keystroke path must hand
    the user's text back once the send is done -- and the CDP path must never
    touch the clipboard at all."""
    api = FakeApi()
    clipboard = FakeClipboard(user_copied="пользователь копировал это")
    result = build(api, clipboard, confirm_timeout=0).deliver(
        session(), "hello there", tab_index=None
    )
    assert result.ok is True
    assert clipboard.value == "пользователь копировал это", (
        "the user's clipboard must come back after the paste"
    )
    assert combos(api) == ["CTRL+V", "ENTER"]


def test_text_never_goes_out_one_keystroke_at_a_time():
    """The clipboard is the transport; per-character typing is the old bug."""
    api = FakeApi()
    build(api, confirm_timeout=0).deliver(session(), "x" * 5000, tab_index=1)
    assert [call for call in api.calls if call[0] == "text"] == []


def antigravity_session(name="_FastPrompter"):
    return Session(
        key="antigravity:abc",
        agent="antigravity",
        name=name,
        project=rf"V:\proj\{name}",
        session_id="abc",
        started=0.0,
        last_active=0.0,
    )


def test_antigravity_window_is_matched_by_its_real_title_not_the_project():
    """Its only window is titled exactly "Antigravity".

    Matching the project name against that produced
    `window not found: ... title contains='_FastPrompter'` on every send.
    """
    api = FakeApi()
    result = build(api, confirm_timeout=0).deliver(
        antigravity_session(), "hi", tab_index=None
    )

    assert result.ok is True
    assert api.calls[0] == ("resolve",) + DEFAULT_WINDOW_TARGETS["antigravity"]
    assert "_FastPrompter" not in str(api.calls[0])


def test_addressing_reports_blind_when_there_is_no_port_and_no_tab():
    """The user has to be told the prompt lands in whatever chat is open."""
    deliverer = build(FakeApi(), cdp_probe=lambda _p: False)
    mode, why = deliverer.addressing(antigravity_session(), None)

    assert mode == "blind"
    assert "вслепую" in why


def test_addressing_reports_tab_when_an_index_is_known():
    deliverer = build(FakeApi(), cdp_probe=lambda _p: False)
    mode, why = deliverer.addressing(session(), 3)
    assert mode == "tab"
    assert "CTRL+3" in why


# ------------------------------------------------------------------- cdp path
class FakeCdpSender:
    def __init__(self, result):
        self.result = result
        self.sent = []

    def send(self, intent, target):
        self.sent.append((intent.text, target))
        return self.result


class FakeResult:
    def __init__(self, ok, reason="", hold=False):
        self.ok = ok
        self.reason = reason
        self.hold = hold


def cdp_deliverer(api, sender, port=22998, monkeypatch=None):
    deliverer = build(api, confirm_timeout=0, cdp_sender=sender,
                      cdp_probe=lambda p: p == port)
    deliverer.cdp_status = lambda agent: (port, "") if port else (0, "нет порта")
    return deliverer


def test_a_live_debugger_port_is_used_instead_of_keystrokes():
    api = FakeApi()
    sender = FakeCdpSender(FakeResult(True, "sent silently over the debugger"))
    deliverer = cdp_deliverer(api, sender)
    deliverer._cdp_target = lambda s: ("page", "")

    result = deliverer.deliver(antigravity_session(), "hi", tab_index=None)

    assert result.ok is True
    assert "debugger" in result.reason
    assert sender.sent == [("hi", "page")]
    assert api.calls == [], "no window was touched at all"


def test_a_cdp_refusal_never_falls_back_to_blind_keystrokes():
    """"There is text in the field already" means wait, not type over it."""
    api = FakeApi()
    sender = FakeCdpSender(
        FakeResult(False, "waiting: there is text in the field already", hold=True)
    )
    deliverer = cdp_deliverer(api, sender)
    deliverer._cdp_target = lambda s: ("page", "")

    result = deliverer.deliver(antigravity_session(), "hi", tab_index=None)

    assert result.ok is False
    assert "there is text in the field already" in result.reason
    assert api.calls == []


def test_no_port_falls_through_to_the_window_path_and_says_why():
    api = FakeApi()
    sender = FakeCdpSender(FakeResult(True, "unused"))
    deliverer = build(api, confirm_timeout=0, cdp_sender=sender,
                      cdp_probe=lambda _p: False)
    deliverer._cdp_target = lambda s: (None, "порт 22998 записан, но не отвечает")

    result = deliverer.deliver(antigravity_session(), "hi", tab_index=None)

    assert result.ok is True
    assert sender.sent == []
    assert any("cdp недоступен" in step for step in result.plan)
    assert combos(api) == ["CTRL+V", "ENTER"]


def test_a_stale_port_file_is_not_treated_as_a_live_port(tmp_path, monkeypatch):
    """Both agents leave the file behind from an older run."""
    port_file = tmp_path / "DevToolsActivePort"
    port_file.write_text("22998\n/devtools/browser/abc", encoding="utf-8")
    monkeypatch.setitem(
        __import__("SAISENT_sessions.deliver", fromlist=["x"]).CDP_PORT_FILES,
        "antigravity",
        str(port_file),
    )

    deliverer = build(FakeApi(), cdp_probe=lambda _p: False)
    port, reason = deliverer.cdp_status("antigravity")

    assert port == 0
    assert "не отвечает" in reason


# ------------------------------------------------------------------ refusals
def test_empty_prompt_is_refused_before_touching_the_keyboard():
    api = FakeApi()
    result = build(api).deliver(session(), "   ", tab_index=1)

    assert result.ok is False
    assert result.reason == "empty prompt"
    assert api.calls == []


def test_unknown_agent_has_no_window_mapping():
    api = FakeApi()
    result = build(api).deliver(session(agent="mystery"), "hi", tab_index=1)

    assert result.ok is False
    assert "no window mapping" in result.reason
    assert api.calls == []


def test_tab_beyond_ctrl_9_is_refused():
    """There is no CTRL+10 -- sending one would type into the wrong tab."""
    api = FakeApi()
    result = build(api).deliver(session(), "hi", tab_index=12)

    assert result.ok is False
    assert "CTRL+1..9" in result.reason
    assert api.calls == []


def test_missing_window_is_reported_not_raised():
    api = FakeApi(resolve_error="Целевое окно не найдено")
    result = build(api).deliver(session(), "hi", tab_index=1)

    assert result.ok is False
    assert "window not found" in result.reason


def test_failed_activation_stops_the_send():
    api = FakeApi(activates=False)
    result = build(api).deliver(session(), "hi", tab_index=1)

    assert result.ok is False
    assert combos(api) == []


def test_focus_lost_after_the_tab_switch_aborts_before_pasting():
    """A dialog stealing focus mid-switch must not get the prompt."""
    api = FakeApi()
    api.foreground_answers = [True, False]
    clipboard = FakeClipboard()
    result = build(api, clipboard, attempts=1).deliver(session(), "secret", tab_index=2)

    assert result.ok is False
    assert "focus moved away" in result.reason
    assert clipboard.value is None
    assert combos(api) == ["CTRL+2"]


# ------------------------------------------------------------- locked desktop
def test_a_locked_desktop_refuses_instead_of_reporting_a_hopeful_ok():
    """The overnight failure: SendInput succeeds into nothing while locked.

    Every keystroke is swallowed, the batch reports OK, and the morning shows
    an empty chat. Refusing with the reason is the only honest answer.
    """
    api = FakeApi()
    deliverer = build(api, attempts=1, desktop_check=lambda: False)

    result = deliverer.deliver(session(), "hi", tab_index=1)

    assert result.ok is False
    assert "заблокирован" in result.reason
    assert api.calls == [], "nothing may be typed at a locked desktop"


def test_an_unlocked_desktop_sends_normally():
    api = FakeApi()
    deliverer = build(api, confirm_timeout=0, desktop_check=lambda: True)

    assert deliverer.deliver(session(), "hi", tab_index=1).ok is True


def test_the_lock_check_does_not_block_a_cdp_send():
    """A debugger send is a socket write; the screen being locked is irrelevant.

    This is the whole reason the debugger is worth the setup: it is the only
    transport that works while the machine is locked.
    """
    api = FakeApi()
    sender = FakeCdpSender(FakeResult(True, "sent silently over the debugger"))
    deliverer = build(api, confirm_timeout=0, cdp_sender=sender,
                      cdp_probe=lambda _p: True, desktop_check=lambda: False)
    deliverer._cdp_target = lambda s: ("page", "")

    result = deliverer.deliver(antigravity_session(), "hi", tab_index=None)

    assert result.ok is True
    assert sender.sent == [("hi", "page")]


# -------------------------------------------------------------------- retries
def test_a_transient_window_failure_is_retried():
    """Minimised, busy, focus stolen for a moment -- worth a second go."""
    api = FakeApi(activates=False)
    deliverer = build(api, attempts=3, retry_delay_ms=0, confirm_timeout=0)

    result = deliverer.deliver(session(), "hi", tab_index=1)

    assert result.ok is False
    activations = [c for c in api.calls if c[0] == "activate"]
    assert len(activations) == 3, "one attempt turns a blip into a stopped batch"


def test_a_retry_that_works_reports_success():
    api = FakeApi(activates=False)
    deliverer = build(api, attempts=3, retry_delay_ms=0, confirm_timeout=0)

    original = api.activate_window

    def flaky(hwnd, timeout_ms):
        original(hwnd, timeout_ms)
        api.activates = True
        return len([c for c in api.calls if c[0] == "activate"]) > 1

    api.activate_window = flaky
    result = deliverer.deliver(session(), "hi", tab_index=1)

    assert result.ok is True


def test_a_refusal_is_not_retried():
    """A bad tab index does not become good by asking twice."""
    api = FakeApi()
    deliverer = build(api, attempts=3, retry_delay_ms=0)

    result = deliverer.deliver(session(), "hi", tab_index=99)

    assert result.ok is False
    assert api.calls == []


def test_clipboard_failure_stops_before_pasting_stale_content():
    api = FakeApi()
    result = build(api, FakeClipboard(ok=False)).deliver(session(), "hi", tab_index=1)

    assert result.ok is False
    assert "clipboard" in result.reason
    assert "CTRL+V" not in combos(api)


# -------------------------------------------------------------- confirmation
def test_confirmation_waits_for_the_session_store_to_move():
    api = FakeApi()
    readings = iter([100.0, 100.0, 100.0, 250.0])
    ticks = iter([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])

    result = Deliverer(
        api,
        clipboard=FakeClipboard(),
        activity=lambda key: next(readings),
        sleep=lambda _s: None,
        clock=lambda: next(ticks),
        confirm_timeout=10.0,
    ).deliver(session(), "hi", tab_index=1)

    assert result.ok is True
    assert result.confirmed is True


def test_no_activity_is_sent_but_unconfirmed_never_a_failure():
    """Chromium answers no WM_GETTEXT; a quiet turn is not a lost prompt."""
    api = FakeApi()
    ticks = iter([0.0, 1.0, 99.0])

    result = Deliverer(
        api,
        clipboard=FakeClipboard(),
        activity=lambda key: 100.0,
        sleep=lambda _s: None,
        clock=lambda: next(ticks),
        confirm_timeout=5.0,
    ).deliver(session(), "hi", tab_index=1)

    assert result.ok is True
    assert result.confirmed is False
    assert "no activity yet" in result.reason


def test_a_throwing_activity_probe_does_not_break_the_send():
    api = FakeApi()

    def boom(key):
        raise RuntimeError("db locked")

    result = Deliverer(
        api,
        clipboard=FakeClipboard(),
        activity=boom,
        sleep=lambda _s: None,
        confirm_timeout=0.0,
    ).deliver(session(), "hi", tab_index=1)

    assert result.ok is True
    assert result.confirmed is False


# ---------------------------------------------------------------- dry runs
def test_dry_run_describes_the_plan_and_touches_nothing():
    api = FakeApi()
    clipboard = FakeClipboard()
    result = build(api, clipboard).deliver(session(), "hi", tab_index=2, dry=True)

    assert result.ok is True
    assert api.calls == []
    assert clipboard.value is None
    assert result.plan == [
        "activate claude.exe / Claude",
        "CTRL+2 (tab of saisent-1)",
        "paste 2 chars",
        "ENTER",
    ]


@pytest.mark.parametrize("agent", sorted(DEFAULT_WINDOW_TARGETS))
def test_every_shipped_agent_maps_to_a_window(agent):
    assert build(FakeApi()).window_for(agent) is not None


# --------------------------------------------- blind send landing elsewhere
def test_a_blind_send_names_the_session_it_actually_reached():
    """Measured 2026-08-06: a send aimed at wintage-f1 landed in saisent-69.

    Reporting that as merely "unconfirmed" hides the useful half — the text
    did arrive, just not where it was aimed.
    """
    api = FakeApi()
    activity = [
        {"claude-code:target": 100.0, "claude-code:other": 100.0},
        {"claude-code:target": 100.0, "claude-code:other": 200.0},
    ]
    deliverer = build(
        api,
        attempts=1,
        confirm_timeout=0,
        activity_map=lambda: activity[min(len(activity) - 1, deliverer_calls[0])],
    )
    deliverer_calls = [0]

    def stepping_map():
        index = min(deliverer_calls[0], len(activity) - 1)
        deliverer_calls[0] += 1
        return activity[index]

    deliverer.activity_map = stepping_map
    target = session(key="claude-code:target")
    target.name = "wintage-f1"

    result = deliverer.deliver(target, "hi", tab_index=None)

    assert result.ok is False
    assert "другую сессию" in result.reason
    assert "claude-code:other" in result.reason


def test_no_stray_movement_stays_an_honest_unconfirmed():
    api = FakeApi()
    snapshot = {"claude-code:target": 100.0, "claude-code:other": 100.0}
    deliverer = build(api, attempts=1, confirm_timeout=0,
                      activity_map=lambda: dict(snapshot))

    result = deliverer.deliver(session(key="claude-code:target"), "hi")

    assert result.ok is True
    assert "no activity yet" in result.reason


def test_two_sessions_moving_at_once_names_neither():
    """Both could be coincidence; a guess here would be worse than silence."""
    api = FakeApi()
    steps = [
        {"a": 1.0, "b": 1.0, "c": 1.0},
        {"a": 1.0, "b": 9.0, "c": 9.0},
    ]
    calls = [0]

    def stepping_map():
        index = min(calls[0], len(steps) - 1)
        calls[0] += 1
        return steps[index]

    deliverer = build(api, attempts=1, confirm_timeout=0,
                      activity_map=stepping_map)

    result = deliverer.deliver(session(key="a"), "hi")

    assert result.ok is True
    assert "другую сессию" not in result.reason
