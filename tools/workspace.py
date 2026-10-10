"""Workspace helpers that keep the agent's file access inside one folder (spec FR-003, FR-004)."""

from pathlib import Path

from agents.errors import InvalidWorkspaceError
from agents.schemas import GeneratedFile

IGNORED_DIRECTORIES = frozenset({"__pycache__"})


def resolve_in_workspace(workspace: Path, relative_path: str) -> Path:
    """Resolve ``relative_path`` against ``workspace``, refusing anything that escapes it.

    Symlinks are resolved first, so a link pointing outside the workspace is refused too.

    Raises:
        ValueError: if the path is absolute or resolves outside the workspace.
    """
    if Path(relative_path).is_absolute():
        raise ValueError(f"absolute paths are not allowed: {relative_path}")
    root = workspace.resolve()
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"path is outside the workspace: {relative_path}")
    return candidate


def prepare_workspace(path: Path | None, root: Path, run_id: str) -> Path:
    """Return a new, empty workspace folder for one task.

    Args:
        path: Folder the caller asked for, or None to create ``root / run_id``.
        root: Parent folder for generated workspaces.
        run_id: Unique id of this run.

    Raises:
        InvalidWorkspaceError: if ``path`` exists and is not an empty directory.
    """
    workspace = path if path is not None else root / run_id
    if workspace.exists() and (not workspace.is_dir() or any(workspace.iterdir())):
        raise InvalidWorkspaceError(
            f"Workspace {workspace} must be missing or an empty folder; "
            "working on existing code is not supported."
        )
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace.resolve()


def list_workspace_files(workspace: Path) -> list[GeneratedFile]:
    """Return every file in the workspace with its contents, sorted by path."""
    root = workspace.resolve()
    files = []
    for file_path in sorted(root.rglob("*")):
        relative = file_path.relative_to(root)
        if not file_path.is_file() or IGNORED_DIRECTORIES.intersection(relative.parts):
            continue
        content = file_path.read_text(encoding="utf-8", errors="replace")
        files.append(GeneratedFile(path=relative.as_posix(), content=content))
    return files
