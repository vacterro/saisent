"""Tests for SAISENT's own agent-sender wiring.

The dangerous path — keystrokes into a real window — is driven through a
fake WindowsAPI, so every branch of SaisentSender.send and the transport
selection in WatcherController._dispatch is exercised without a single key
ever reaching an application.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from types import SimpleNamespace  # noqa: E402

from SAISENT_GUI import (  # noqa: E402
    SaisentSender,
    SaisentTarget,
    WatcherController,
)
from SAISENT_watcher.queue import PENDING, SENT  # noqa: E402


# ------------------------------------------------------------------ helpers

class FakeAPI:
    """Records what a real WindowsAPI would have sent."""

    def __init__(self, resolve_ok=True, activate_ok=True,
                 foreground_ok=True, raise_on_send=False, lands=True):
        self.resolve_ok = resolve_ok
        self.activate_ok = activate_ok
        self.foreground_ok = foreground_ok
        self.raise_on_send = raise_on_send
        # False = the control never reflects what was typed; read-back
        # then returns empty, exactly like a console host.
        self.lands = lands
        self.sent_texts = []
        self.sent_combos = []
        self.resolved = None

    def resolve_target(self, exe, cls, title):
        self.resolved = (exe, cls, title)
        if not self.resolve_ok:
            raise RuntimeError(f"Целевое окно не найдено: {title}.")
        return SimpleNamespace(hwnd=1, title=title or "T")

    def activate_window(self, hwnd, timeout_ms):
        return self.activate_ok

    def is_foreground(self, hwnd):
        return self.foreground_ok

    def send_text(self, text, delay_ms):
        if self.raise_on_send:
            raise RuntimeError("send_text boom")
        self.sent_texts.append(text)

    def read_target_text(self, hwnd):
        if not self.lands:
            return ""
        return self.sent_texts[-1] if self.sent_texts else ""

    def send_combo(self, combo, delay_ms):
        self.sent_combos.append(combo)


def intent(text="Привет, агент"):
    return SimpleNamespace(
        item_id="abc123", queue_key="q", skill="", text=text)


def target(title="Claude"):
    return SaisentTarget("claude.exe", "Chrome_WidgetWin_1", title)


def make_controller(api, **kw):
    # A temp dir by default: a test that forgets tmpdir must not drop
    # s.json / s.queue.jsonl into the project root.
    tmpdir = kw.pop("tmpdir", None) or tempfile.mkdtemp()
    wc = WatcherController(
        api=api,
        on_log=lambda *a, **k: None,
        on_status=lambda *a, **k: None,
        state_path=os.path.join(tmpdir, "s.json"),
    )
    wc.adapter_transport = kw.pop("transport", "post")
    wc.target = target()
    return wc


# ------------------------------------------------------------- SaisentSender

def test_send_ok_types_and_submits():
    api = FakeAPI()
    sender = SaisentSender(api)
    result = sender.send(intent("Hello"), target())
    assert result.ok
    assert result.text == "Hello"
    assert api.sent_texts == ["Hello"]
    assert api.sent_combos == ["ENTER"]


def test_send_ok_with_custom_submit():
    api = FakeAPI()
    sender = SaisentSender(api, submit="CTRL+ENTER")
    result = sender.send(intent(), target())
    assert result.ok
    assert api.sent_combos == ["CTRL+ENTER"]


def test_send_no_target_configured():
    api = FakeAPI()
    sender = SaisentSender(api)
    result = sender.send(intent(), None)
    assert not result.ok
    assert result.reason == "no target configured"
    assert api.sent_texts == []


def test_send_unresolved_window_fails():
    api = FakeAPI(resolve_ok=False)
    sender = SaisentSender(api)
    result = sender.send(intent(), target())
    assert not result.ok
    assert "send failed" in result.reason
    assert api.sent_texts == []


def test_send_activation_failure():
    api = FakeAPI(activate_ok=False)
    sender = SaisentSender(api)
    result = sender.send(intent(), target())
    assert not result.ok
    assert result.reason == "could not activate the target window"
    assert api.sent_texts == []


def test_send_focus_loss_aborts():
    api = FakeAPI(foreground_ok=False)
    sender = SaisentSender(api)
    result = sender.send(intent(), target())
    assert not result.ok
    assert result.reason == "the target lost focus"
    assert api.sent_texts == []


def test_send_exception_is_not_silent():
    api = FakeAPI(raise_on_send=True)
    sender = SaisentSender(api)
    result = sender.send(intent(), target())
    assert not result.ok
    assert "send failed" in result.reason


# --------------------------------------------------- read-back, added in T-007

def test_send_that_lands_nowhere_is_held_not_sent():
    """T-007: the GUI post path must apply the same rule cdp.py and
    PostMessageSender enforce — a send that lands nowhere is a HOLD, never
    reported sent, and the submit key is not pressed."""
    api = FakeAPI(lands=False)
    sender = SaisentSender(api)
    result = sender.send(intent("Hello"), target())
    assert not result.ok
    assert result.hold is True
    assert "did not reach" in result.reason
    assert api.sent_combos == [], "no submit on an unconfirmed send"


def test_unconfirmed_gui_sends_escalate_to_failure():
    """T-007: the same cap as PostMessageSender — after N unconfirmed sends
    in a row the hold becomes a real failure so a dead target surfaces."""
    api = FakeAPI(lands=False)
    sender = SaisentSender(api, max_unconfirmed=3)
    for _ in range(2):
        result = sender.send(intent(), target())
        assert result.hold is True, "still patient on the first two"
    result = sender.send(intent(), target())
    assert not result.ok
    assert result.hold is False
    assert "never confirmed" in result.reason


def test_a_success_resets_the_unconfirmed_count():
    api = FakeAPI()
    sender = SaisentSender(api, max_unconfirmed=2)
    sender.send(intent("Hello"), target())
    assert sender._unconfirmed == 0


def test_dispatch_gui_post_hold_keeps_item_pending():
    """T-007 verify: recorder-based — a GUI post send that lands nowhere
    stays PENDING in the queue."""
    api = FakeAPI(lands=False)
    wc = make_controller(api, transport="post")
    wc.add_prompt("Hello")
    intent, item = _arm_and_tick(wc, api)
    assert intent is not None
    wc._dispatch(intent)
    assert item.state == PENDING, "held, never marked sent"
    assert api.sent_combos == [], "nothing was submitted"
    wc.disarm()


# --------------------------------------------- WatcherController._dispatch

def _arm_and_tick(wc, tmpdir, until_intent=True, max_ticks=60):
    """Прогнать движок до появления intent (или до конца окна), вернуть
    (intent, item).

    Движок шлёт только после того, как увидел агента работающим (_seen_busy),
    поэтому файл-проба получает два разных токена: "x" при арме (baseline),
    потом "y" — смена = работа агента, затем тишина = idle -> settle -> intent.
    """
    import tempfile
    import time as _time
    probe_dir = tempfile.mkdtemp()
    probe = os.path.join(probe_dir, "idle.txt")
    with open(probe, "w") as fh:
        fh.write("x")
    wc.set_probe("file", probe, quiet_ms=0)
    ok, _ = wc.arm()
    assert ok
    base = _time.monotonic()
    first = True
    for i in range(max_ticks):
        now = base + 0.5 + i * 0.5
        if first:
            first = False
            wc.engine.tick(now, wc.queue)          # baseline
            with open(probe, "w") as fh:
                fh.write("y")                     # агент поработал
            continue
        if wc._limit_blocked()[0]:
            continue
        intent = wc.engine.tick(now, wc.queue)
        if intent is not None:
            return intent, wc.queue.items[0]
    return None, wc.queue.items[0]


def test_dispatch_post_transport_sends_via_win32():
    api = FakeAPI()
    wc = make_controller(api, transport="post")
    wc.add_prompt("Hello")
    intent, item = _arm_and_tick(wc, api)
    assert intent is not None
    wc._dispatch(intent)
    assert api.sent_texts == ["Hello"]
    assert item.state == SENT
    wc.disarm()


def test_dispatch_cdp_dead_port_holds_item():
    """Мёртвый cdp-порт: промпт не жжётся — остаётся pending в очереди,
    и НЕ уходит в Win32-окно."""
    api = FakeAPI()
    wc = make_controller(api, transport="cdp")
    wc.cdp_port = 0            # порт не задан -> target недоступен
    wc.cdp_port_file = ""
    wc.add_prompt("Hello")
    intent, item = _arm_and_tick(wc, api)
    assert intent is not None
    wc._dispatch(intent)
    assert item.state == PENDING          # hold, а не failed
    assert api.sent_texts == []           # в окно ничего не ушло
    wc.disarm()


def test_dispatch_cdp_unreachable_port_holds():
    api = FakeAPI()
    wc = make_controller(api, transport="cdp")
    wc.cdp_port = 1            # 127.0.0.1:1 никогда не слушает DevTools
    wc.add_prompt("Hello")
    intent, item = _arm_and_tick(wc, api)
    assert intent is not None
    wc._dispatch(intent)
    assert item.state == PENDING
    assert api.sent_texts == []
    wc.disarm()


def test_dispatch_cdp_without_sender_holds_not_win32():
    """Транспорт cdp, но отправитель не настроен: hold, а не Win32-фолбэк."""
    api = FakeAPI()
    wc = make_controller(api, transport="cdp")
    wc._cdp_sender = None      # симулируем state без cdp-отправителя
    wc.add_prompt("Hello")
    intent, item = _arm_and_tick(wc, api)
    assert intent is not None
    wc._dispatch(intent)
    assert item.state == PENDING
    assert api.sent_texts == []
    wc.disarm()


def test_dispatch_send_log_records_target_title():
    api = FakeAPI()
    wc = make_controller(api, transport="post")
    wc.target.title_contains = "Claude"
    wc.add_prompt("Hello")
    intent, _ = _arm_and_tick(wc, api)
    assert intent is not None
    wc._dispatch(intent)
    entry = wc.send_history(1)[0]
    assert entry["ok"] is True
    assert entry["target"] == "Claude"
    wc.disarm()


# --------------------------------------------- per-dialog queues (T-0xx)

def test_add_prompt_routes_to_dialog_queue():
    api = FakeAPI()
    wc = make_controller(api, transport="post")
    wc.add_prompt("to A", dialog="A")
    wc.add_prompt("to B", dialog="B")
    wc.add_prompt("legacy")
    assert [i.text for i in wc.dialog_queues["A"].items] == ["to A"]
    assert [i.text for i in wc.dialog_queues["B"].items] == ["to B"]
    assert [i.text for i in wc.queue.items] == ["legacy"]
    # the item carries the dialog name for the CDP sender
    assert wc.dialog_queues["A"].items[0].dialog == "A"
    wc.disarm()


def test_prompts_show_dialog_label_and_flat_order():
    api = FakeAPI()
    wc = make_controller(api, transport="post")
    wc.add_prompt("first")
    wc.add_prompt("b", dialog="B")
    wc.add_prompt("a", dialog="A")
    assert wc.prompts() == ["first", "[A] a", "[B] b"]
    wc.disarm()


def test_remove_prompt_indexes_flat_list():
    api = FakeAPI()
    wc = make_controller(api, transport="post")
    wc.add_prompt("legacy")
    wc.add_prompt("b", dialog="B")
    wc.add_prompt("a", dialog="A")
    assert wc.remove_prompt(0) is True       # legacy gone
    assert wc.remove_prompt(1) is True       # [B] gone (flat order: A before B)
    assert wc.prompts() == ["[A] a"]
    assert wc.remove_prompt(5) is False      # out of range
    wc.disarm()


def test_pick_queue_round_robins_across_dialogs():
    api = FakeAPI()
    wc = make_controller(api, transport="post")
    wc.add_prompt("x", dialog="A")
    wc.add_prompt("y", dialog="B")
    wc.add_prompt("z")
    seen = [wc._pick_queue(), wc._pick_queue(), wc._pick_queue()]
    # legacy first, then dialogs in sorted order, then back around
    assert seen[0] is wc.queue
    assert seen[1] is wc.dialog_queues["A"]
    assert seen[2] is wc.dialog_queues["B"]
    wc.disarm()


def test_pick_queue_skips_empty_queues():
    api = FakeAPI()
    wc = make_controller(api, transport="post")
    wc.add_prompt("x", dialog="A")   # only this one has work
    for _ in range(5):
        assert wc._pick_queue() is wc.dialog_queues["A"]
    wc.disarm()


def test_dispatch_finds_item_in_dialog_queue():
    api = FakeAPI()
    wc = make_controller(api, transport="post")
    wc.add_prompt("Hello", dialog="A")
    # reuse the arm helper: it ticks wc.queue, so seed the same text there
    wc.add_prompt("Hello")
    intent, _ = _arm_and_tick(wc, api)
    assert intent is not None
    # put the intent's id into the dialog queue and dispatch: the item
    # must be found across ALL queues, not just the legacy one
    item = wc.dialog_queues["A"].items[0]
    intent.item_id = item.id
    wc.engine.state = "sending"
    wc._dispatch(intent)
    assert item.state == SENT
    assert api.sent_texts == ["Hello"]
    wc.disarm()


def test_dialog_queues_survive_state_roundtrip(tmp_path):
    api = FakeAPI()
    wc = make_controller(api, transport="post", tmpdir=str(tmp_path))
    wc.add_prompt("to A", dialog="A")
    wc.add_prompt("legacy")
    assert wc.save_state()
    # a fresh controller on the same state file must recover both queues
    wc2 = make_controller(FakeAPI(), transport="post", tmpdir=str(tmp_path))
    wc2.load_state()
    assert [i.text for i in wc2.dialog_queues["A"].items] == ["to A"]
    assert [i.text for i in wc2.queue.items] == ["legacy"]
    wc.disarm()
    wc2.disarm()
