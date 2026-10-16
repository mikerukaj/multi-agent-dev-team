"""The team graph: PM → Coder handoffs, progress in shared state, final run (spec US1–US3)."""

import pytest
from langchain_core.messages import AIMessage

from agents.errors import InvalidRequirementError, InvalidWorkspaceError, LLMServiceError
from agents.schemas import (
    CoderResult,
    ExecutionPlan,
    ExecutionResult,
    ExecutionStatus,
    ExplanationDraft,
    PlanDecision,
    StopReason,
)
from config import MAX_REVISIONS
from orchestration.protocol import (
    OutcomeStatus,
    SpecificationDraft,
    TaskRecord,
    TaskReport,
    TaskStatus,
    build_handoff,
)
from orchestration.team_graph import (
    TEAM_RECURSION_LIMIT,
    _TeamNodes,
    build_team_graph,
    run_dev_team,
)
from tests.conftest import make_specification, tool_call_message

REQUIREMENT = "Build a command-line clock"
CLOCK = (
    "from datetime import datetime, timezone\n\n\n"
    "def now_text():\n"
    "    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')\n"
)
MAIN = "from clock import now_text\n\nprint(now_text())\n"


def _coder_structured() -> list:
    return [
        PlanDecision(steps=["Write", "Run"], is_coding_task=True),
        ExplanationDraft(explanation="Explanation."),
    ]


def _write(path: str, content: str, call_id: str) -> AIMessage:
    return tool_call_message("Writing.", "write_file", {"path": path, "content": content}, call_id)


def _run(call_id: str) -> AIMessage:
    return tool_call_message("Running.", "exec_python", {"path": "main.py"}, call_id)


def _two_task_dependencies(make_dependencies):
    """T1 writes clock.py (nothing to run yet); T2 writes and runs main.py."""
    draft = SpecificationDraft(is_software_requirement=True, specification=make_specification(2))
    responses = [
        _write("clock.py", CLOCK, "t1-w"),
        AIMessage(content="clock.py is ready."),
        _write("main.py", MAIN, "t2-w"),
        _run("t2-r"),
        AIMessage(content="main.py prints the time."),
    ]
    return make_dependencies(responses, [draft, *_coder_structured(), *_coder_structured()])


def _invoke(dependencies, workspace) -> dict:
    graph = build_team_graph(dependencies, workspace)
    return graph.invoke(
        {"run_id": "run1", "requirement": REQUIREMENT},
        {"recursion_limit": TEAM_RECURSION_LIMIT},
    )


def test_two_task_run_hands_off_in_order_and_records_progress(make_dependencies, workspace):
    final_state = _invoke(_two_task_dependencies(make_dependencies), workspace)
    result = final_state["result"]

    first, second = result.tasks
    assert [first.task.id, second.task.id] == ["T1", "T2"]
    for record in result.tasks:
        assert record.status == TaskStatus.COMPLETED
        assert record.handoff is not None and record.report is not None
        assert record.report.task_id == record.handoff.task_id == record.task.id
    assert first.handoff.workspace_files == []
    assert second.handoff.workspace_files == ["clock.py"]
    assert [file.path for file in result.code] == ["clock.py", "main.py"]
    assert result.execution_result.success, result.execution_result.stderr
    assert result.outcome.status == OutcomeStatus.COMPLETED
    assert final_state["current_handoff"] is None


def test_report_for_wrong_task_stops_the_run(make_dependencies, workspace):
    specification = make_specification(2)
    handoff = build_handoff(specification, specification.tasks[0], "run1", [])
    wrong_report = TaskReport(
        task_id="T2",
        status=TaskStatus.COMPLETED,
        coder_result=CoderResult(
            code=[],
            explanation="Explanation.",
            plan=ExecutionPlan(
                steps=["Step"], iterations=1, revision_attempts=0, stop_reason=StopReason.COMPLETED
            ),
            execution_result=ExecutionResult.not_run(),
        ),
    )
    state = {
        "run_id": "run1",
        "tasks": [TaskRecord(task=task) for task in specification.tasks],
        "current_handoff": handoff,
        "last_report": wrong_report,
    }
    nodes = _TeamNodes(make_dependencies(), workspace)
    with pytest.raises(LLMServiceError, match=r"T2.*T1"):
        nodes.record_report(state)


def test_empty_requirement_raises_before_any_work(make_dependencies, settings):
    dependencies = make_dependencies()
    with pytest.raises(InvalidRequirementError):
        run_dev_team("   ", dependencies=dependencies)
    assert dependencies.llm.calls == []
    assert not settings.workspace_root.exists()


def test_non_empty_workspace_is_rejected_before_any_model_call(make_dependencies, workspace):
    (workspace / "existing.py").write_text("print('hi')\n")
    dependencies = make_dependencies()
    with pytest.raises(InvalidWorkspaceError):
        run_dev_team(REQUIREMENT, workspace=workspace, dependencies=dependencies)
    assert dependencies.llm.calls == []


def test_declined_requirement_returns_a_declined_result(make_dependencies, workspace):
    declined = SpecificationDraft(
        is_software_requirement=False,
        decline_reason="Only standard-library Python programs can be built.",
    )
    dependencies = make_dependencies(structured=[declined])

    result = run_dev_team("Build a React web app", workspace=workspace, dependencies=dependencies)

    assert result.outcome.status == OutcomeStatus.DECLINED
    assert "standard-library Python" in result.outcome.reason
    assert result.specification is None and result.tasks == [] and result.code == []
    assert result.execution_result.status == ExecutionStatus.NOT_RUN
    assert dependencies.llm.tool_bound_calls == 0
    assert not any(workspace.iterdir())


def test_failed_task_stops_later_handoffs(make_dependencies, workspace):
    draft = SpecificationDraft(is_software_requirement=True, specification=make_specification(2))
    bad = "raise SystemExit(1)\n"
    responses = [_write("main.py", bad, "w"), *[_run(f"r{n}") for n in range(MAX_REVISIONS + 1)]]
    dependencies = make_dependencies(responses, [draft, *_coder_structured()])

    result = run_dev_team(REQUIREMENT, workspace=workspace, dependencies=dependencies)

    first, second = result.tasks
    assert first.status == TaskStatus.FAILED
    assert first.report.coder_result.plan.stop_reason == StopReason.REVISION_LIMIT
    assert second.status == TaskStatus.NOT_STARTED and second.handoff is None
    assert result.outcome.status == OutcomeStatus.FAILED
    assert "T1" in result.outcome.reason
    assert result.execution_result.status == ExecutionStatus.FAILED  # the final run still happens


def test_helper_only_task_completes_and_no_entry_point_means_not_run(make_dependencies, workspace):
    # Spec US3 scenario 5 and FR-016: nothing to run yet is fine, and no main.py means not run.
    draft = SpecificationDraft(is_software_requirement=True, specification=make_specification(1))
    responses = [_write("clock.py", CLOCK, "w"), AIMessage(content="clock.py is ready.")]
    dependencies = make_dependencies(responses, [draft, *_coder_structured()])

    result = run_dev_team(REQUIREMENT, workspace=workspace, dependencies=dependencies)

    assert result.tasks[0].status == TaskStatus.COMPLETED
    assert result.execution_result.status == ExecutionStatus.NOT_RUN
    assert result.outcome.status == OutcomeStatus.COMPLETED


def test_coder_failure_names_the_task(make_dependencies, workspace):
    draft = SpecificationDraft(is_software_requirement=True, specification=make_specification(1))
    # No scripted Coder responses: the Coder's first reasoning call fails inside task T1.
    plan = PlanDecision(steps=["Write"], is_coding_task=True)
    dependencies = make_dependencies([], [draft, plan])
    with pytest.raises(LLMServiceError, match=r"^Task T1 failed: Model call failed:"):
        run_dev_team(REQUIREMENT, workspace=workspace, dependencies=dependencies)
