"""read_file / write_file tools confined to the task workspace (contracts/tools.md)."""

from pathlib import Path

from langchain_core.tools import BaseTool, tool

from config import Settings
from tools.workspace import resolve_in_workspace


def make_file_tools(workspace: Path, settings: Settings) -> list[BaseTool]:
    """Return the ``read_file`` and ``write_file`` tools bound to ``workspace``.

    Both tools return ``ERROR: <reason>`` text instead of raising, so the model sees the problem
    as an observation.
    """

    @tool
    def read_file(path: str) -> str:
        """Read a text file from the workspace. `path` is relative to the workspace."""
        try:
            content = resolve_in_workspace(workspace, path).read_text(encoding="utf-8")
        except (ValueError, OSError, UnicodeDecodeError) as error:
            return f"ERROR: cannot read {path}: {error}"
        return truncate_for_observation(content, settings.max_observation_chars)

    @tool
    def write_file(path: str, content: str) -> str:
        """Write (or overwrite) a text file in the workspace. Parent folders are created."""
        try:
            target = resolve_in_workspace(workspace, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except (ValueError, OSError) as error:
            return f"ERROR: cannot write {path}: {error}"
        return f"Wrote {len(content)} characters to {path}"

    return [read_file, write_file]


def truncate_for_observation(text: str, limit: int) -> str:
    """Cut ``text`` to ``limit`` characters, noting how much was dropped."""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n... [truncated {len(text) - limit} characters]"
