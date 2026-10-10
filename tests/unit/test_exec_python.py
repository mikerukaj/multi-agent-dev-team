"""exec_python sandboxed runner (contracts/tools.md, spec FR-005, FR-005a, FR-006)."""

import os
import time
from pathlib import Path

import pytest

from agents.schemas import ExecutionStatus
from tools.exec_python import format_execution_observation, make_exec_python_tool, run_python_file

TIMEOUT = 5.0
MAX_CHARS = 1_000


def _run(workspace: Path, source: str, timeout: float = TIMEOUT):
    (workspace / "main.py").write_text(source)
    return run_python_file(workspace, "main.py", timeout, MAX_CHARS)


def test_success_captures_stdout(workspace):
    result = _run(workspace, "print('hello')")
    assert result.status == ExecutionStatus.SUCCEEDED
    assert result.success and result.exit_code == 0
    assert result.stdout == "hello\n"
    assert result.entrypoint == "main.py"


def test_non_zero_exit_is_failed(workspace):
    result = _run(workspace, "raise SystemExit(3)")
    assert result.status == ExecutionStatus.FAILED
    assert result.exit_code == 3 and not result.success


def test_input_gets_end_of_file_instead_of_hanging(workspace):
    start = time.monotonic()
    result = _run(workspace, "input('name? ')")
    assert time.monotonic() - start < TIMEOUT
    assert result.status == ExecutionStatus.FAILED
    assert "EOFError" in result.stderr


def test_timeout_kills_process_and_its_children(workspace):
    pid_file = workspace / "child.pid"
    source = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    result = _run(workspace, source, timeout=1)
    assert result.status == ExecutionStatus.TIMED_OUT
    assert result.exit_code is None and not result.success

    child_pid = int(pid_file.read_text())
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and _is_alive(child_pid):
        time.sleep(0.1)
    assert not _is_alive(child_pid)


def test_large_output_is_truncated(workspace):
    result = _run(workspace, f"print('x' * {MAX_CHARS * 20})")
    assert result.truncated
    assert len(result.stdout) <= MAX_CHARS + 100


def test_secrets_are_not_passed_to_generated_code(workspace, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    result = _run(workspace, "import os; print(os.environ.get('ANTHROPIC_API_KEY'))")
    assert result.stdout == "None\n"


def test_main_can_import_sibling_modules(workspace):
    (workspace / "helper.py").write_text("VALUE = 42\n")
    result = _run(workspace, "from helper import VALUE; print(VALUE)")
    assert result.stdout == "42\n"


def test_tool_refuses_paths_outside_workspace(workspace, settings):
    tool = make_exec_python_tool(workspace, settings)
    message = tool.invoke(
        {"name": "exec_python", "args": {"path": "../x.py"}, "id": "1", "type": "tool_call"}
    )
    assert message.content.startswith("ERROR:")
    assert message.artifact is None


def test_tool_returns_text_and_result_artifact(workspace, settings):
    (workspace / "main.py").write_text("print('hi')")
    tool = make_exec_python_tool(workspace, settings)
    message = tool.invoke(
        {"name": "exec_python", "args": {"path": "main.py"}, "id": "1", "type": "tool_call"}
    )
    assert message.content == format_execution_observation(message.artifact)
    assert message.content.startswith("status=succeeded exit_code=0")
    assert "stdout:\nhi\n" in message.content


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        with open(f"/proc/{pid}/stat") as stat:
            return stat.read().split()[2] != "Z"
    except FileNotFoundError:
        return False


@pytest.fixture(autouse=True)
def _no_leftover_pid_files(workspace):
    yield
    for path in workspace.glob("*.pid"):
        path.unlink()
