"""Loop limits and honest failure reporting (spec US2, FR-006, FR-009, FR-010)."""

from dataclasses import replace

from langchain_core.messages import AIMessage

from agents.coder_agent import run_coder_agent
from agents.schemas import ExecutionStatus, ExplanationDraft, PlanDecision, StopReason
from config import MAX_ITERATIONS
from tests.conftest import tool_call_message

TASK = "Write a python program"
GOOD = "print('ok')"
BAD = "raise SystemExit(1)"


def _structured():
    return [
        PlanDecision(steps=["Write", "Run"], is_coding_task=True),
        ExplanationDraft(explanation="Explanation."),
    ]


def _write(source: str, call_id: str):
    return tool_call_message(
        "Writing.", "write_file", {"path": "main.py", "content": source}, call_id
    )


def _run(call_id: str):
    return tool_call_message("Running.", "exec_python", {"path": "main.py"}, call_id)


def _agent(make_dependencies, workspace, responses, timeout: float | None = None):
    dependencies = make_dependencies(responses, _structured())
    if timeout is not None:
        dependencies = replace(
            dependencies, settings=replace(dependencies.settings, exec_timeout_seconds=timeout)
        )
    result = run_coder_agent(TASK, workspace=workspace, dependencies=dependencies)
    return result, dependencies.llm


def test_iteration_limit_stops_after_ten_rounds(make_dependencies, workspace):
    responses = [
        tool_call_message("Look again.", "read_file", {"path": "notes.txt"}, f"r{n}")
        for n in range(MAX_ITERATIONS + 5)
    ]
    result, llm = _agent(make_dependencies, workspace, responses)
    assert result.plan.stop_reason == StopReason.ITERATION_LIMIT
    assert result.plan.iterations == MAX_ITERATIONS
    assert llm.tool_bound_calls == MAX_ITERATIONS
    assert all(step.action is not None for step in result.plan.trace)


def test_revision_limit_after_initial_run_and_three_revisions(make_dependencies, workspace):
    responses = [_write(BAD, "w"), _run("e1"), _run("e2"), _run("e3"), _run("e4")]
    result, llm = _agent(make_dependencies, workspace, responses)
    assert result.plan.stop_reason == StopReason.REVISION_LIMIT
    assert result.plan.revision_attempts == 3
    assert llm.tool_bound_calls == 5
    assert result.execution_result.success is False


def test_recovery_after_one_revision(make_dependencies, workspace):
    responses = [
        _write(BAD, "w1"),
        _run("e1"),
        _write(GOOD, "w2"),
        _run("e2"),
        AIMessage(content="Fixed."),
    ]
    result, _ = _agent(make_dependencies, workspace, responses)
    assert result.plan.revision_attempts == 1
    assert result.plan.stop_reason == StopReason.COMPLETED
    assert result.execution_result.success


def test_giving_up_without_revising_counts_no_revisions(make_dependencies, workspace):
    responses = [_write(BAD, "w1"), _run("e1"), AIMessage(content="I give up.")]
    result, _ = _agent(make_dependencies, workspace, responses)
    assert result.plan.revision_attempts == 0
    assert result.execution_result.success is False
    assert result.execution_result.status == ExecutionStatus.FAILED


def test_revisions_never_exceed_limit_after_recovery(make_dependencies, workspace):
    responses = [
        _write(BAD, "w1"),
        _run("e1"),
        _write(GOOD, "w2"),
        _run("e2"),
        _run("e3"),
        _run("e4"),
        AIMessage(content="Not reached."),
    ]
    result, llm = _agent(make_dependencies, workspace, responses)
    assert result.plan.revision_attempts == 3
    assert result.plan.stop_reason == StopReason.COMPLETED
    assert llm.tool_bound_calls == 6


def test_stale_run_is_repeated_by_finalize(make_dependencies, workspace):
    responses = [
        _write("print(1)", "w1"),
        _run("e1"),
        _write("print(2)", "w2"),
        AIMessage(content="Done."),
    ]
    result, _ = _agent(make_dependencies, workspace, responses)
    assert result.execution_result.stdout == "2\n"


def test_code_never_run_is_run_by_finalize(make_dependencies, workspace):
    responses = [_write(GOOD, "w1"), AIMessage(content="Done.")]
    result, _ = _agent(make_dependencies, workspace, responses)
    assert result.execution_result.success
    assert result.execution_result.stdout == "ok\n"


def test_timeout_is_reported_as_failure(make_dependencies, workspace):
    responses = [
        _write("import time; time.sleep(30)", "w1"),
        _run("e1"),
        AIMessage(content="Done."),
    ]
    result, _ = _agent(make_dependencies, workspace, responses, timeout=1)
    assert result.execution_result.status == ExecutionStatus.TIMED_OUT
    assert result.execution_result.success is False
