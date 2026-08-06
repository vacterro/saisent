"""Undo last send: mark/unmark cycle for undoing a sent prompt."""

from __future__ import annotations

from SAISENT_sessions.queues import STATE_PENDING, STATE_SENT, QueueStore


def store(tmp_path, name="undo.json"):
    return QueueStore(tmp_path / name)


def test_undo_restores_pending_when_sent_and_unconfirmed(tmp_path):
    q = store(tmp_path)
    q.add("s:a", "hello")
    item = q.items("s:a")[0]
    q.mark("s:a", item.id, STATE_SENT, "ok", confirmed=False)
    assert q.find("s:a", item.id).state == STATE_SENT
    assert not q.find("s:a", item.id).confirmed
    item2 = q.find("s:a", item.id)
    item2.state = STATE_PENDING
    item2.reason = ""
    item2.sent_at = ""
    item2.confirmed = False
    q.save()
    reloaded = store(tmp_path)
    reloaded.load()
    restored = reloaded.find("s:a", item.id)
    assert restored.state == STATE_PENDING
    assert restored.reason == ""
    assert restored.sent_at == ""
    assert not restored.confirmed


def test_undo_refused_when_item_confirmed(tmp_path):
    q = store(tmp_path)
    q.add("s:a", "hello")
    item = q.items("s:a")[0]
    q.mark("s:a", item.id, STATE_SENT, "ok", confirmed=True)
    assert q.find("s:a", item.id).confirmed
    # Confirmed item should not be undone


def test_undo_refused_when_item_not_sent(tmp_path):
    q = store(tmp_path)
    q.add("s:a", "hello")
    item = q.items("s:a")[0]
    assert item.state == STATE_PENDING
    # Pending items are not "undoable" (only sent items can be undone)


def test_undo_refused_when_item_gone(tmp_path):
    q = store(tmp_path)
    assert q.find("s:gone", "nonexistent") is None
