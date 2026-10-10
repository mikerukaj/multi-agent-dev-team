"""exec_python: run a workspace Python file in a separate, time-limited process (research R7).

This is process isolation only, not a security boundary: the generated program can still use
the network and read files the user can read. The project's container is the real boundary
(spec FR-005a).
"""

import contextlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from langchain_core.tools import BaseTool, tool

from agents.schemas import ExecutionResult, ExecutionStatus
from config import Settings
from tools.workspace import resolve_in_workspace

ALLOWED_ENVIRONMENT_VARIABLES = ("PATH", "HOME", "LANG", "TZ")
"""Only these are passed to generated code, so secrets such as ANTHROPIC_API_KEY are not."""

PYTHON_FLAGS = ("-E", "-s")
"""Ignore PYTHON* env variables and user site-packages. (-I is not used because it also drops
the script's folder from sys.path, which breaks multi-file programs.)"""


def run_python_file(
    workspace: Path, relative_path: str, timeout_seconds: float, max_output_chars: int
) -> ExecutionResult:
    """Run ``relative_path`` with the current interpreter and report what happened.

    Raises:
        ValueError: if the path is outside the workspace.
        FileNotFoundError: if the file does not exist.
    """
    script = resolve_in_workspace(workspace, relative_path)
    if not script.is_file():
        raise FileNotFoundError(f"{relative_path} does not exist")

    started = time.monotonic()
    process = subprocess.Popen(
        [sys.executable, *PYTHON_FLAGS, str(script)],
        cwd=workspace,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_child_environment(),
        start_new_session=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        timed_out = False
    except subprocess.TimeoutExpired:
        _kill_process_group(process.pid)
        stdout, stderr = process.communicate()
        timed_out = True
    duration = round(time.monotonic() - started, 3)

    stdout, stdout_cut = _truncate(stdout, max_output_chars)
    stderr, stderr_cut = _truncate(stderr, max_output_chars)
    if timed_out:
        status, exit_code = ExecutionStatus.TIMED_OUT, None
    else:
        exit_code = process.returncode
        status = ExecutionStatus.SUCCEEDED if exit_code == 0 else ExecutionStatus.FAILED
    return ExecutionResult(
        status=status,
        success=status == ExecutionStatus.SUCCEEDED,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        truncated=stdout_cut or stderr_cut,
        duration_seconds=duration,
        entrypoint=relative_path,
    )


def format_execution_observation(result: ExecutionResult) -> str:
    """Summarize a run as text for the model (format in contracts/tools.md)."""
    exit_code = "none" if result.exit_code is None else result.exit_code
    return (
        f"status={result.status} exit_code={exit_code} duration={result.duration_seconds}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def make_exec_python_tool(workspace: Path, settings: Settings) -> BaseTool:
    """Return the ``exec_python`` tool bound to ``workspace``.

    The tool's text goes to the model; the full ``ExecutionResult`` is attached as the tool
    message's artifact (``None`` on errors).
    """

    @tool(response_format="content_and_artifact")
    def exec_python(path: str) -> tuple[str, ExecutionResult | None]:
        """Run a Python file from the workspace and return its exit status and output."""
        try:
            result = run_python_file(
                workspace, path, settings.exec_timeout_seconds, settings.max_output_chars
            )
        except (ValueError, OSError) as error:
            return f"ERROR: cannot run {path}: {error}", None
        return format_execution_observation(result), result

    return exec_python


def _child_environment() -> dict[str, str]:
    return {name: os.environ[name] for name in ALLOWED_ENVIRONMENT_VARIABLES if name in os.environ}


def _kill_process_group(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError):  # Already exited.
        os.killpg(pid, signal.SIGKILL)


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return f"{text[:limit]}\n... [truncated {len(text) - limit} characters]", True
