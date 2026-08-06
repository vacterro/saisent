"""The app must actually start.

Every other test imports modules and calls functions, so the whole suite was
green at 524 while `SAISENT.pyw` died on launch with
`NameError: name 'FONT_BUTTON' is not defined` -- a name used in the UI build
and never re-exported. Nothing that skips widget construction can catch that.

So this one builds the real window, then tears it down. It is slow and it
flashes on screen; it is also the only test that would have noticed.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
tk = pytest.importorskip("tkinter")


@pytest.fixture(scope="module")
def app_module():
    spec = importlib.util.spec_from_file_location(
        "saisent_app_under_test", ROOT / "SAISENT.pyw"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["saisent_app_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def app(app_module, tmp_path, monkeypatch):
    """A real window, pointed at throwaway files, with the pollers muzzled.

    The quota scan opens transcripts and probes debugger sockets, and the tray
    runs its own message loop. Left alive they turned a 7-second suite into 65
    seconds of real I/O plus `main thread is not in main loop` on teardown.
    None of that is what this test is about: it checks that the window builds.
    """
    monkeypatch.setattr(app_module, "CONFIG_PATH", tmp_path / "SAISENT.json")
    monkeypatch.setattr(app_module, "QUEUE_PATH", tmp_path / "queues.json")
    monkeypatch.setattr(app_module, "LOG_PATH", tmp_path / "SAISENT.log")
    monkeypatch.setattr(
        app_module.SaisentApp, "tick_limits", lambda self: None, raising=True
    )
    monkeypatch.setattr(
        app_module.SaisentApp,
        "start_limit_scan",
        lambda self, force=False: None,
        raising=True,
    )

    class NoTray:
        def __init__(self, *a, **k):
            pass

        def start(self, *a, **k):
            return True

        def stop(self):
            return None

    monkeypatch.setattr(app_module.core, "TrayIcon", NoTray, raising=True)

    # Prove a display exists FIRST, then let construction errors fail loudly.
    # Skipping on any TclError meant a real build bug -- a heading for an
    # undeclared column, `Invalid column index fire` -- was reported as
    # "headless CI" and the suite stayed green while the app would not open.
    try:
        probe = tk.Tk()
        probe.withdraw()
        probe.destroy()
    except tk.TclError as exc:  # pragma: no cover - headless CI
        pytest.skip(f"no display: {exc}")

    window = app_module.SaisentApp()
    window.auto_var.set(False)
    window.apply_auto_refresh()
    window.update()

    yield window

    window.closing = True
    for attr in ("_limit_after", "_auto_after"):
        handle = getattr(window, attr, None)
        if handle:
            try:
                window.after_cancel(handle)
            except Exception:
                pass
    try:
        window.destroy()
    except Exception:
        pass


def test_the_window_builds(app):
    assert app.winfo_exists()
    assert app.session_tree is not None
    assert app.queue_tree is not None
    assert app.text_box is not None


def test_the_send_path_is_wired(app):
    assert app.deliverer is not None
    assert app.worker is not None
    assert app.worker.registry is app.registry
    assert app.worker.limit_monitor is app.limit_monitor
    assert app.deliverer.activity_map is not None


def test_the_settings_dialog_opens(app):
    app.show_more()
    app.update()
    dialogs = [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)]
    assert len(dialogs) == 1
    for dialog in dialogs:
        dialog.destroy()


def test_queueing_and_reordering_survive_a_round_trip(app):
    key = "claude-code:test-session"
    app.selected_key = key
    app.text_box.insert("1.0", "первый")
    app.add_to_queue()
    app.text_box.insert("1.0", "второй")
    app.add_to_queue()
    app.update()

    assert [i.text for i in app.queues.items(key)] == ["первый", "второй"]

    second = app.queues.items(key)[1]
    app.queue_tree.selection_set(second.id)
    app.move_item(-1)

    assert [i.text for i in app.queues.items(key)] == ["второй", "первый"]
