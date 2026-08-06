"""Tests for SAISENT_watcher.queue — per-silo prompt queues."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from SAISENT_watcher import queue as q  # noqa: E402
from SAISENT_watcher.queue import (  # noqa: E402
    DETACHED,
    FAILED,
    PENDING,
    SENT,
    SKIPPED,
    QueueItem,
    SiloQueue,
)


def make(*texts):
    return SiloQueue([QueueItem(t) for t in texts])


# ------------------------------------------------------------------ items

def test_an_item_starts_pending_with_an_id():
    item = QueueItem("continue please")
    assert item.state == PENDING
    assert item.id and len(item.id) == 12
    assert item.created


def test_a_leading_slash_on_the_skill_is_not_stored_twice():
    """The chip may be written either way; the format string supplies the
    slash, so storing it as well would compose "//saipen"."""
    assert QueueItem("go", skill="/saipen").skill == "saipen"
    assert QueueItem("go", skill="saipen").skill == "saipen"


def test_compose_prepends_the_skill():
    item = QueueItem("continue please.", skill="saipen")
    assert item.compose() == "/saipen continue please."


def test_compose_without_a_skill_is_the_bare_text():
    assert QueueItem("just this").compose() == "just this"


def test_compose_refuses_when_the_target_has_no_skills():
    """Sending it stripped would be a different request than the one that
    was queued, so the caller must skip it instead."""
    item = QueueItem("continue", skill="saipen")
    assert item.compose(skill_format=None) is None
    # ...but a skill-less item is fine on such a target
    assert QueueItem("continue").compose(skill_format=None) == "continue"


def test_compose_honours_a_different_invocation_syntax():
    item = QueueItem("go", skill="review")
    assert item.compose("!{skill}: {text}") == "!review: go"


def test_state_transitions_carry_a_reason():
    item = QueueItem("x")
    item.mark_failed("window vanished")
    assert (item.state, item.reason) == (FAILED, "window vanished")
    item.mark_skipped()
    assert item.state == SKIPPED and item.reason
    item.mark_detached()
    assert item.state == DETACHED and "deleted" in item.reason
    item.mark_sent()
    assert item.state == SENT and item.sent_at and item.reason == ""
    item.reset()
    assert item.state == PENDING and item.sent_at is None and item.reason == ""


# ------------------------------------------------------------------ order

def test_order_is_explicit_and_never_sorted():
    queue = make("c", "a", "b")
    assert [i.text for i in queue] == ["c", "a", "b"]


def test_move_clamps_instead_of_raising():
    queue = make("a", "b", "c")
    last = queue.items[-1]
    assert queue.move(last.id, 99) is True
    assert [i.text for i in queue] == ["a", "b", "c"]
    assert queue.move(last.id, -5) is True
    assert [i.text for i in queue] == ["c", "a", "b"]


def test_to_front_is_send_next_not_send_now():
    """It may only jump the queue. Nothing here types into the agent."""
    queue = make("a", "b", "c")
    third = queue.items[2]
    assert queue.to_front(third.id) is True
    assert [i.text for i in queue] == ["c", "a", "b"]
    assert third.state == PENDING, "jumping the queue must not send it"


def test_move_and_remove_on_a_missing_id_are_no_ops():
    queue = make("a")
    assert queue.move("nope", 0) is False
    assert queue.remove("nope") is None
    assert len(queue) == 1


def test_next_pending_skips_everything_that_had_its_turn():
    queue = make("a", "b", "c", "d")
    queue.items[0].mark_sent()
    queue.items[1].mark_failed()
    queue.items[2].mark_skipped()
    assert queue.next_pending().text == "d"


def test_a_failed_item_stays_in_place():
    """An error does not stop the queue: the item is marked and the next one
    goes, but it is not removed - the user must still see what failed."""
    queue = make("a", "b")
    queue.items[0].mark_failed("timeout")
    assert len(queue) == 2
    assert queue.next_pending().text == "b"
    assert queue.items[0].reason == "timeout"


def test_a_detached_item_is_not_sent_but_is_kept():
    queue = make("a", "b")
    queue.items[0].mark_detached()
    assert queue.next_pending().text == "b"
    assert queue.items[0].text == "a", "the last known text must survive"


def test_next_pending_on_an_exhausted_queue_is_none():
    queue = make("a")
    queue.items[0].mark_sent()
    assert queue.next_pending() is None


# ------------------------------------------------------------ persistence

def test_round_trip_preserves_order_and_state():
    queues = {"0": make("first", "second"), "3": make("other")}
    queues["0"].items[0].skill = "saipen"
    queues["0"].items[1].mark_failed("nope")

    back = q.load_queues(q.save_queues(queues))
    assert sorted(back) == ["0", "3"]
    assert [i.text for i in back["0"]] == ["first", "second"]
    assert back["0"].items[0].skill == "saipen"
    assert back["0"].items[1].state == FAILED
    assert back["0"].items[1].reason == "nope"


def test_empty_queues_are_not_stored():
    """Empty containers accumulate in saved data and confuse everything that
    reads it - the same reason childless parents are pruned elsewhere."""
    saved = q.save_queues({"0": SiloQueue(), "1": make("x")})
    assert list(saved) == ["1"]


def test_corrupt_entries_are_skipped_not_fatal():
    raw = {"0": [{"text": "good"}, {"no_text": 1}, "junk", None, 42]}
    back = q.load_queues(raw)
    assert [i.text for i in back["0"]] == ["good"]


def test_junk_at_the_top_level_is_survivable():
    assert q.load_queues(None) == {}
    assert q.load_queues([]) == {}
    assert q.load_queues({"0": "not a list"}) == {}


def test_an_unknown_state_falls_back_to_pending():
    back = q.load_queues({"0": [{"text": "x", "state": "wat"}]})
    assert back["0"].items[0].state == PENDING


def test_ids_survive_a_round_trip():
    """The UI refers to rows by id; regenerating them on load would break a
    selection every time the app restarts."""
    queues = {"0": make("a")}
    original = queues["0"].items[0].id
    back = q.load_queues(q.save_queues(queues))
    assert back["0"].items[0].id == original


# ------------------------------------------------------------ JSONL store

def test_jsonl_round_trip_keeps_pending_items_across_a_fresh_load(tmp_path):
    """T-001 verify: enqueue two items, re-run the queue module fresh, both
    still PENDING with the same text."""
    path = tmp_path / "queues.jsonl"
    queues = {"0": make("first", "second")}
    assert q.save_queues_jsonl(path, queues) == 2

    fresh = q.load_queues_jsonl(path)
    assert sorted(fresh) == ["0"]
    assert [i.text for i in fresh["0"]] == ["first", "second"]
    assert all(i.state == PENDING for i in fresh["0"])
    assert fresh["0"].items[0].id == queues["0"].items[0].id


def test_jsonl_round_trip_preserves_state_and_skill(tmp_path):
    path = tmp_path / "queues.jsonl"
    queues = {"0": make("a", "b")}
    queues["0"].items[0].skill = "saipen"
    queues["0"].items[1].mark_failed("nope")
    q.save_queues_jsonl(path, queues)

    fresh = q.load_queues_jsonl(path)
    assert fresh["0"].items[0].skill == "saipen"
    assert (fresh["0"].items[1].state,
            fresh["0"].items[1].reason) == (FAILED, "nope")


def test_jsonl_multi_silo_order_is_slot_then_position(tmp_path):
    path = tmp_path / "queues.jsonl"
    q.save_queues_jsonl(path, {"9": make("nine"), "2": make("two")})
    fresh = q.load_queues_jsonl(path)
    assert sorted(fresh) == ["2", "9"]
    assert [i.text for i in fresh["2"]] == ["two"]


def test_jsonl_corrupt_lines_are_skipped_not_fatal(tmp_path):
    path = tmp_path / "queues.jsonl"
    path.write_text(
        '{"slot": "0", "item": {"text": "good"}}\n'
        "not json\n"
        "{\"slot\": \"0\", \"item\": {}}\n",
        encoding="utf-8")
    fresh = q.load_queues_jsonl(path)
    assert [i.text for i in fresh["0"]] == ["good"]


def test_jsonl_missing_or_empty_file_is_an_empty_store(tmp_path):
    assert q.load_queues_jsonl(tmp_path / "nope.jsonl") == {}
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n\n", encoding="utf-8")
    assert q.load_queues_jsonl(empty) == {}


def test_jsonl_saving_an_empty_store_removes_the_file(tmp_path):
    """An empty store must not linger and read back as a corrupted one."""
    path = tmp_path / "queues.jsonl"
    path.write_text("stale\n", encoding="utf-8")
    assert q.save_queues_jsonl(path, {}) == 0
    assert not path.exists()


# ------------------------------------------------------------ master view

def test_all_items_orders_by_slot_then_position():
    queues = {"2": make("b1", "b2"), "0": make("a1")}
    rows = q.all_items(queues)
    assert [(slot, item.text) for slot, _label, item in rows] == [
        ("0", "a1"), ("2", "b1"), ("2", "b2"),
    ]


def test_slots_sort_numerically_not_as_text():
    queues = {"10": make("ten"), "9": make("nine"), "2": make("two")}
    assert [s for s, _l, _i in q.all_items(queues)] == ["2", "9", "10"]


def test_all_items_carries_the_silo_label():
    queues = {"0": make("x")}
    rows = q.all_items(queues, labels={"0": "Project notes"})
    assert rows[0][1] == "Project notes"


def test_move_between_silos():
    queues = {"0": make("a", "b"), "1": make("c")}
    moved = queues["0"].items[1]
    assert q.move_between(queues, moved.id, "0", "1") is True
    assert [i.text for i in queues["0"]] == ["a"]
    assert [i.text for i in queues["1"]] == ["c", "b"]


def test_move_between_can_target_a_position():
    queues = {"0": make("a"), "1": make("x", "y")}
    moved = queues["0"].items[0]
    q.move_between(queues, moved.id, "0", "1", index=0)
    assert [i.text for i in queues["1"]] == ["a", "x", "y"]


def test_move_between_creates_the_destination_queue():
    queues = {"0": make("a")}
    moved = queues["0"].items[0]
    assert q.move_between(queues, moved.id, "0", "7") is True
    assert [i.text for i in queues["7"]] == ["a"]


def test_move_between_with_a_bad_source_is_a_no_op():
    queues = {"0": make("a")}
    assert q.move_between(queues, "nope", "0", "1") is False
    assert q.move_between(queues, "nope", "99", "1") is False
    assert len(queues["0"]) == 1


# ------------------------------------------------------------ slot keying

def test_the_store_is_keyed_the_way_the_other_slot_maps_are():
    """Same shape as silo_colors and friends ({slot: value}), so an index
    remap goes through main.py's existing `str_dict` handling instead of
    needing its own."""
    saved = q.save_queues({"3": make("x")})
    assert list(saved) == ["3"]
    assert isinstance(list(saved)[0], str)
    assert isinstance(saved["3"], list)
