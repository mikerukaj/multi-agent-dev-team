"""read_file / write_file tools (contracts/tools.md, spec FR-004, SC-005)."""

import pytest

from tools.file_tools import make_file_tools


@pytest.fixture
def file_tools(workspace, settings):
    return {tool.name: tool for tool in make_file_tools(workspace, settings)}


def test_write_creates_parent_folders(file_tools, workspace):
    result = file_tools["write_file"].invoke({"path": "pkg/util.py", "content": "x = 1\n"})
    assert result == "Wrote 6 characters to pkg/util.py"
    assert (workspace / "pkg" / "util.py").read_text() == "x = 1\n"


def test_read_returns_contents(file_tools, workspace):
    (workspace / "main.py").write_text("print('hi')\n")
    assert file_tools["read_file"].invoke({"path": "main.py"}) == "print('hi')\n"


def test_read_truncates_long_files(file_tools, workspace, settings):
    (workspace / "big.txt").write_text("a" * (settings.max_observation_chars + 50))
    result = file_tools["read_file"].invoke({"path": "big.txt"})
    assert result.startswith("a" * settings.max_observation_chars)
    assert "truncated" in result


def test_missing_file_is_an_error_not_an_exception(file_tools):
    assert file_tools["read_file"].invoke({"path": "nope.py"}).startswith("ERROR:")


@pytest.mark.parametrize("path", ["../escape.py", "/tmp/escape.py", "link/escape.py"])
def test_paths_outside_workspace_are_refused(file_tools, workspace, tmp_path, path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "link").symlink_to(outside)
    before = sorted(p.name for p in tmp_path.rglob("*"))

    assert file_tools["write_file"].invoke({"path": path, "content": "x"}).startswith("ERROR:")
    assert file_tools["read_file"].invoke({"path": path}).startswith("ERROR:")

    assert sorted(p.name for p in tmp_path.rglob("*")) == before
    assert not list(outside.iterdir())
