"""Per-session prompt queues: order is the send order, and it survives."""

from __future__ import annotations

from SAISENT_sessions.queues import (
    STATE_FAILED,
    STATE_PENDING,
    STATE_SENT,
    PromptItem,
    QueueStore,
)


def store(tmp_path, name="queues.json"):
    return QueueStore(tmp_path / name)


def test_add_keeps_insertion_order_per_session(tmp_path):
    queue = store(tmp_path)
    queue.add("s:one", "first")
    queue.add("s:one", "second")
    queue.add("s:two", "other")

    assert [i.text for i in queue.items("s:one")] == ["first", "second"]
    assert [i.text for i in queue.items("s:two")] == ["other"]


def test_add_rejects_empty_text_and_missing_key(tmp_path):
    queue = store(tmp_path)
    assert queue.add("s:one", "   ") is None
    assert queue.add("", "text") is None
    assert queue.items("s:one") == []


def test_move_shifts_and_clamps(tmp_path):
    queue = store(tmp_path)
    a = queue.add("s", "a")
    queue.add("s", "b")
    c = queue.add("s", "c")

    assert queue.move("s", c.id, -1) is True
    assert [i.text for i in queue.items("s")] == ["a", "c", "b"]

    # Already at the top: clamped, and reported as "nothing moved".
    assert queue.move("s", a.id, -5) is False
    assert [i.text for i in queue.items("s")] == ["a", "c", "b"]


def test_move_to_places_an_item_at_an_absolute_position(tmp_path):
    """This is what a drag produces: a target row, not a delta."""
    queue = store(tmp_path)
    queue.add("s", "a")
    queue.add("s", "b")
    c = queue.add("s", "c")

    assert queue.move_to("s", c.id, 0) is True
    assert [i.text for i in queue.items("s")] == ["c", "a", "b"]

    assert queue.move_to("s", c.id, 99) is True
    assert [i.text for i in queue.items("s")] == ["a", "b", "c"]


def test_next_pending_skips_sent_items(tmp_path):
    queue = store(tmp_path)
    first = queue.add("s", "a")
    queue.add("s", "b")

    queue.mark("s", first.id, STATE_SENT)
    assert queue.next_pending("s").text == "b"


def test_failed_items_stay_in_line_for_a_retry(tmp_path):
    queue = store(tmp_path)
    first = queue.add("s", "a")
    queue.mark("s", first.id, STATE_FAILED, "window vanished")

    assert queue.next_pending("s").id == first.id
    assert queue.find("s", first.id).reason == "window vanished"


def test_mark_sent_stamps_the_time(tmp_path):
    queue = store(tmp_path)
    item = queue.add("s", "a")
    queue.mark("s", item.id, STATE_SENT)

    assert queue.find("s", item.id).sent_at != ""


def test_edit_rewrites_in_place_without_moving_the_item(tmp_path):
    queue = store(tmp_path)
    queue.add("s", "a")
    middle = queue.add("s", "b")
    queue.add("s", "c")

    assert queue.edit("s", middle.id, "b, but better") is True
    assert [i.text for i in queue.items("s")] == ["a", "b, but better", "c"]


def test_editing_a_sent_item_makes_it_pending_again(tmp_path):
    """The row no longer holds what the session received; `sent` would lie."""
    queue = store(tmp_path)
    item = queue.add("s", "typo")
    queue.mark("s", item.id, STATE_SENT)

    assert queue.edit("s", item.id, "fixed") is True
    fixed = queue.find("s", item.id)
    assert fixed.state == STATE_PENDING
    assert fixed.sent_at == ""


def test_edit_refuses_empty_text_and_unchanged_text(tmp_path):
    queue = store(tmp_path)
    item = queue.add("s", "a")

    assert queue.edit("s", item.id, "   ") is False
    assert queue.edit("s", item.id, "a") is False
    assert queue.edit("s", "no-such-id", "x") is False
    assert queue.find("s", item.id).text == "a"


def test_duplicate_lands_directly_below_the_original(tmp_path):
    queue = store(tmp_path)
    queue.add("s", "a")
    middle = queue.add("s", "b")
    queue.add("s", "c")

    clone = queue.duplicate("s", middle.id)

    assert [i.text for i in queue.items("s")] == ["a", "b", "b", "c"]
    assert clone.id != middle.id
    assert clone.state == STATE_PENDING


def test_duplicate_of_a_sent_item_is_pending(tmp_path):
    queue = store(tmp_path)
    item = queue.add("s", "again")
    queue.mark("s", item.id, STATE_SENT)

    clone = queue.duplicate("s", item.id)
    assert clone.state == STATE_PENDING
    assert queue.find("s", item.id).state == STATE_SENT


def test_duplicate_of_a_missing_item_is_none(tmp_path):
    queue = store(tmp_path)
    queue.add("s", "a")
    assert queue.duplicate("s", "nope") is None
    assert queue.duplicate("other", "nope") is None


def test_requeue_all_puts_finished_items_back(tmp_path):
    queue = store(tmp_path)
    a = queue.add("s", "a")
    b = queue.add("s", "b")
    queue.mark("s", a.id, STATE_SENT)
    queue.mark("s", b.id, STATE_FAILED, "nope")

    assert queue.requeue_all("s") == 2
    assert [i.state for i in queue.items("s")] == [STATE_PENDING, STATE_PENDING]
    assert queue.find("s", b.id).reason == ""


def test_clear_finished_keeps_pending_work(tmp_path):
    queue = store(tmp_path)
    a = queue.add("s", "a")
    queue.add("s", "b")
    queue.mark("s", a.id, STATE_SENT)

    assert queue.clear_finished("s") == 1
    assert [i.text for i in queue.items("s")] == ["b"]


def test_round_trip_through_disk_preserves_order_and_state(tmp_path):
    queue = store(tmp_path)
    first = queue.add("s:one", "first", label="one-1")
    queue.add("s:one", "second")
    queue.mark("s:one", first.id, STATE_SENT)
    assert queue.save() is True

    reloaded = store(tmp_path)
    assert reloaded.load() is True
    assert [i.text for i in reloaded.items("s:one")] == ["first", "second"]
    assert reloaded.items("s:one")[0].state == STATE_SENT
    assert reloaded.labels["s:one"] == "one-1"


def test_reload_resets_an_interrupted_send(tmp_path):
    """`sending` is not a resting state -- a crash mid-send leaves pending."""
    queue = store(tmp_path)
    item = queue.add("s", "a")
    queue.mark("s", item.id, "sending")
    queue.save()

    reloaded = store(tmp_path)
    reloaded.load()
    assert reloaded.items("s")[0].state == STATE_PENDING


def test_load_of_a_corrupt_file_is_false_not_a_crash(tmp_path):
    path = tmp_path / "queues.json"
    path.write_text("{ not json", encoding="utf-8")

    queue = QueueStore(path)
    assert queue.load() is False
    assert queue.queues == {}


def test_load_drops_entries_with_no_text(tmp_path):
    path = tmp_path / "queues.json"
    path.write_text(
        '{"version":1,"queues":{"s":[{"text":""},{"text":"real"},"junk"]}}',
        encoding="utf-8",
    )
    queue = QueueStore(path)
    queue.load()
    assert [i.text for i in queue.items("s")] == ["real"]


def test_prune_never_drops_a_queue_that_still_has_pending_work(tmp_path):
    """Agents get restarted. A queue must not empty itself while they are down."""
    queue = store(tmp_path)
    queue.add("gone-but-pending", "still waiting")
    done = queue.add("gone-and-done", "already sent")
    queue.mark("gone-and-done", done.id, STATE_SENT)
    queue.add("alive", "keep me")

    dropped = queue.prune(["alive"])

    assert dropped == ["gone-and-done"]
    assert queue.items("gone-but-pending") != []
    assert queue.items("alive") != []


def test_total_pending_counts_across_sessions(tmp_path):
    queue = store(tmp_path)
    queue.add("a", "1")
    queue.add("a", "2")
    sent = queue.add("b", "3")
    queue.mark("b", sent.id, STATE_SENT)

    assert queue.total_pending() == 2
    assert queue.keys_with_pending() == ["a"]


def test_label_flattens_to_one_line():
    item = PromptItem(text="line one\n\n   line two\ttabbed")
    assert item.label == "line one line two tabbed"

    long_item = PromptItem(text="x" * 200)
    assert len(long_item.label) == 90
    assert long_item.label.endswith("...")
