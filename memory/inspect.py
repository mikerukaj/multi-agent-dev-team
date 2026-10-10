"""Inspect or wipe the agent's long-term memory (spec FR-012a).

Usage:
    python -m memory.inspect --last 10
    python -m memory.inspect --wipe [--yes]
"""

import argparse
import sys
from collections.abc import Callable

from config import load_settings
from memory.semantic_memory import SemanticMemory

PREVIEW_CHARS = 120


def main(
    argv: list[str] | None = None,
    memory: SemanticMemory | None = None,
    confirm: Callable[[str], str] = input,
) -> int:
    """Run the command. ``memory`` and ``confirm`` are injectable for tests."""
    parser = argparse.ArgumentParser(description="Inspect or wipe the Coder agent's memory.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--last", type=int, metavar="N", help="Show the N most recent records.")
    action.add_argument("--wipe", action="store_true", help="Delete every stored record.")
    parser.add_argument("--yes", action="store_true", help="Wipe without asking to confirm.")
    args = parser.parse_args(argv)

    memory = memory or SemanticMemory.from_settings(load_settings())
    if args.wipe:
        return _wipe(memory, args.yes, confirm)
    for record in memory.recent(args.last):
        preview = record.text.replace("\n", " ")[:PREVIEW_CHARS]
        print(f"{record.created_at}  {record.run_id}  {record.kind:<11}  {preview}")
    return 0


def _wipe(memory: SemanticMemory, skip_confirmation: bool, confirm: Callable[[str], str]) -> int:
    count = memory.count()
    if not skip_confirmation:
        answer = confirm(f"Delete all {count} memory records? Type 'yes' to confirm: ")
        if answer.strip().lower() != "yes":
            print("Cancelled; memory unchanged.")
            return 1
    removed = memory.wipe()
    print(f"Removed {removed} memory records.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
