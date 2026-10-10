"""Workspace confinement and preparation (spec FR-003, FR-004)."""

import pytest

from agents.errors import InvalidWorkspaceError
from tools.workspace import list_workspace_files, prepare_workspace, resolve_in_workspace


def test_resolve_accepts_nested_relative_path(workspace):
    assert resolve_in_workspace(workspace, "pkg/a.py") == (workspace / "pkg/a.py").resolve()


@pytest.mark.parametrize("path", ["../x.py", "/etc/passwd", "pkg/../../x.py"])
def test_resolve_rejects_escapes(workspace, path):
    with pytest.raises(ValueError):
        resolve_in_workspace(workspace, path)


def test_resolve_rejects_symlink_pointing_outside(workspace, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "link").symlink_to(outside)
    with pytest.raises(ValueError):
        resolve_in_workspace(workspace, "link/file.py")


def test_prepare_creates_run_folder(tmp_path):
    created = prepare_workspace(None, tmp_path / "root", "run-1")
    assert created == (tmp_path / "root" / "run-1").resolve()
    assert created.is_dir()


def test_prepare_accepts_missing_or_empty_folder(tmp_path, workspace):
    assert prepare_workspace(tmp_path / "new", tmp_path, "unused").is_dir()
    assert prepare_workspace(workspace, tmp_path, "unused") == workspace.resolve()


def test_prepare_rejects_folder_with_files(workspace, tmp_path):
    (workspace / "existing.py").write_text("x = 1")
    with pytest.raises(InvalidWorkspaceError):
        prepare_workspace(workspace, tmp_path, "unused")


def test_list_files_skips_pycache(workspace):
    (workspace / "main.py").write_text("print(1)")
    (workspace / "__pycache__").mkdir()
    (workspace / "__pycache__" / "main.cpython-312.pyc").write_bytes(b"\x00")
    files = list_workspace_files(workspace)
    assert [(f.path, f.content) for f in files] == [("main.py", "print(1)")]
