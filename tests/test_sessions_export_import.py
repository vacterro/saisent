"""Export/import: round-trip and merge semantics for QueueStore."""

from __future__ import annotations

from SAISENT_sessions.queues import PromptItem, QueueStore


def store(tmp_path, name="queues.json"):
    return QueueStore(tmp_path / name)


def test_export_writes_valid_jsonl(tmp_path):
    q = store(tmp_path)
    q.add("s:a", "hello")
    q.add("s:a", "world")
    q.add("s:b", "other")
    out = tmp_path / "export.jsonl"
    written = q.export_jsonl(out)
    assert written == 3
    raw = out.read_text(encoding="utf-8")
    lines = [line for line in raw.splitlines() if line.strip()]
    assert len(lines) == 3


def test_export_empty_removes_file(tmp_path):
    q = store(tmp_path)
    out = tmp_path / "none.jsonl"
    out.write_text("junk")
    written = q.export_jsonl(out)
    assert written == 0
    assert not out.exists()


def test_import_adds_new_items(tmp_path):
    q = store(tmp_path)
    out = tmp_path / "pack.jsonl"
    q.add("s:a", "hello")
    q.export_jsonl(out)
    q2 = store(tmp_path, "fresh.json")
    added = q2.import_jsonl(out)
    assert added == 1
    assert [i.text for i in q2.items("s:a")] == ["hello"]


def test_import_skips_duplicates(tmp_path):
    q = store(tmp_path)
    q.add("s:a", "hello")
    out = tmp_path / "pack.jsonl"
    q.export_jsonl(out)
    added = q.import_jsonl(out)
    assert added == 0
    assert len(q.items("s:a")) == 1


def test_import_merges_without_data_loss(tmp_path):
    q = store(tmp_path)
    q.add("s:a", "existing")
    out = tmp_path / "pack.jsonl"
    q.export_jsonl(out)
    q2 = store(tmp_path, "fresh.json")
    q2.add("s:b", "other")
    added = q2.import_jsonl(out)
    assert added == 1
    assert [i.text for i in q2.items("s:a")] == ["existing"]
    assert [i.text for i in q2.items("s:b")] == ["other"]


def test_import_skips_corrupt_file(tmp_path):
    q = store(tmp_path)
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{not valid json\n", encoding="utf-8")
    added = q.import_jsonl(bad)
    assert added == 0


def test_import_missing_file_returns_zero(tmp_path):
    q = store(tmp_path)
    added = q.import_jsonl(tmp_path / "nope.jsonl")
    assert added == 0


def test_round_trip_preserves_item_text_and_keys(tmp_path):
    q = store(tmp_path)
    q.add("s:1", "one")
    q.add("s:1", "two")
    q.add("s:2", "three")
    out = tmp_path / "round.jsonl"
    q.export_jsonl(out)
    q2 = store(tmp_path, "fresh.json")
    q2.import_jsonl(out)
    assert sorted(q2.queues) == sorted(q.queues)
    for key in q.queues:
        assert [i.text for i in q2.items(key)] == [i.text for i in q.items(key)]


def test_export_preserves_item_text_with_special_chars(tmp_path):
    q = store(tmp_path)
    q.add("s:x", "hello\nworld")
    q.add("s:x", '{"json": "like"}')
    out = tmp_path / "spec.jsonl"
    written = q.export_jsonl(out)
    assert written == 2
    q2 = store(tmp_path, "fresh.json")
    added = q2.import_jsonl(out)
    assert added == 2
    texts = [i.text for i in q2.items("s:x")]
    assert "hello\nworld" in texts
    assert '{"json": "like"}' in texts
