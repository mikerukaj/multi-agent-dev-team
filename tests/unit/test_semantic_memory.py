"""Chroma-backed long-term memory (research R4, spec FR-012a)."""

from memory.semantic_memory import MemoryRecord, SemanticMemory


def _record(text: str, kind: str = "observation", created_at: str = "") -> MemoryRecord:
    if created_at:
        return MemoryRecord(kind=kind, text=text, run_id="run-1", created_at=created_at)
    return MemoryRecord(kind=kind, text=text, run_id="run-1")


def test_retrieve_returns_matching_record_first(memory):
    memory.add([_record("timezone los angeles datetime"), _record("fibonacci recursion numbers")])
    results = memory.retrieve("los angeles timezone", top_k=2, max_distance=10.0)
    assert results[0] == "timezone los angeles datetime"


def test_max_distance_filters_unrelated_records(memory):
    memory.add([_record("fibonacci recursion numbers")])
    assert memory.retrieve("los angeles timezone", top_k=4, max_distance=0.5) == []


def test_empty_store_and_blank_texts(memory):
    assert memory.retrieve("anything", top_k=4, max_distance=10.0) == []
    memory.add([_record("   ")])
    assert memory.count() == 0


def test_recent_orders_newest_first(memory):
    memory.add(
        [
            _record("old", created_at="2026-01-01T00:00:00+00:00"),
            _record("new", created_at="2026-02-01T00:00:00+00:00"),
        ]
    )
    assert [record.text for record in memory.recent(2)] == ["new", "old"]


def test_wipe_empties_store(memory):
    memory.add([_record("a"), _record("b")])
    assert memory.wipe() == 2
    assert memory.count() == 0


def test_memory_persists_between_store_instances(memory, settings, fake_embedding):
    memory.add([_record("persisted context")])
    reopened = SemanticMemory.from_settings(settings, embedding_function=fake_embedding)
    assert reopened.retrieve("persisted context", top_k=1, max_distance=10.0) == [
        "persisted context"
    ]
