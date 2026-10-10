"""The memory inspect / wipe command (spec FR-012a)."""

from memory.inspect import main
from memory.semantic_memory import MemoryRecord


def _fill(memory) -> None:
    memory.add(
        [
            MemoryRecord(kind="task", text="oldest", run_id="r", created_at="2026-01-01T00:00:00"),
            MemoryRecord(kind="plan", text="middle", run_id="r", created_at="2026-01-02T00:00:00"),
            MemoryRecord(
                kind="result", text="newest", run_id="r", created_at="2026-01-03T00:00:00"
            ),
        ]
    )


def test_last_prints_newest_first(memory, capsys):
    _fill(memory)
    assert main(["--last", "2"], memory=memory) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert "newest" in lines[0] and "middle" in lines[1]


def test_wipe_with_yes_empties_store(memory, capsys):
    _fill(memory)
    assert main(["--wipe", "--yes"], memory=memory) == 0
    assert memory.count() == 0
    assert "Removed 3" in capsys.readouterr().out


def test_wipe_without_confirmation_keeps_memory(memory):
    _fill(memory)
    assert main(["--wipe"], memory=memory, confirm=lambda prompt: "no") == 1
    assert memory.count() == 3


def test_wipe_with_typed_confirmation(memory):
    _fill(memory)
    assert main(["--wipe"], memory=memory, confirm=lambda prompt: "yes") == 0
    assert memory.count() == 0
