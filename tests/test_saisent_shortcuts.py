"""Keyboard shortcuts: bindings fire correct actions."""

from __future__ import annotations

import tkinter as tk


class FakeTree:
    def __init__(self, items):
        self._items = list(items)
        self._selection = set()
        self._seen = []

    def get_children(self, _=""):
        return list(self._items)

    def selection_set(self, item):
        self._selection = {item}

    def see(self, item):
        self._seen.append(item)


class FakeApp:
    def __init__(self, session_count=5):
        self.session_tree = FakeTree([f"I00{i}" for i in range(1, session_count + 1)])
        self.called_select = False

    def on_session_selected(self):
        self.called_select = True


def _make_jump(app, n):
    """Replicate the closure pattern from SAISENT.pyw."""

    def jump(_event=None):
        children = app.session_tree.get_children("")
        if 0 < n <= len(children):
            item = children[n - 1]
            app.session_tree.selection_set(item)
            app.session_tree.see(item)
            app.on_session_selected()
        return "break"

    return jump


def test_jump_selects_correct_item():
    app = FakeApp(5)
    jump = _make_jump(app, 3)
    jump()
    assert "I003" in app.session_tree._selection
    assert app.called_select


def test_jump_clamps_to_range_below():
    app = FakeApp(3)
    jump = _make_jump(app, 0)
    jump()
    assert not app.session_tree._selection


def test_jump_clamps_to_range_above():
    app = FakeApp(3)
    jump = _make_jump(app, 99)
    jump()
    assert not app.session_tree._selection


def test_jump_sees_the_item():
    app = FakeApp(5)
    jump = _make_jump(app, 5)
    jump()
    assert "I005" in app.session_tree._seen


def test_jump_returns_break():
    app = FakeApp(3)
    jump = _make_jump(app, 1)
    result = jump()
    assert result == "break"
