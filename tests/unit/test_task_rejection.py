"""Rejecting tasks the agent cannot act on (spec US3, FR-011)."""

import pytest

from agents.coder_agent import run_coder_agent
from agents.errors import InvalidTaskError, LLMServiceError
from agents.schemas import ExecutionStatus, PlanDecision, StopReason


@pytest.mark.parametrize("task", ["", "   \n"])
def test_empty_task_raises_before_any_work(make_dependencies, settings, task):
    dependencies = make_dependencies()
    with pytest.raises(InvalidTaskError):
        run_coder_agent(task, dependencies=dependencies)
    assert dependencies.llm.calls == []
    assert not settings.workspace_root.exists()


def test_non_coding_request_is_rejected(make_dependencies, workspace):
    decision = PlanDecision(
        steps=["Rejected: not a coding request"],
        is_coding_task=False,
        rejection_reason="Not a coding request",
    )
    dependencies = make_dependencies(structured=[decision])

    result = run_coder_agent("What is your favourite colour?", workspace, dependencies=dependencies)

    assert result.plan.stop_reason == StopReason.REJECTED
    assert result.code == []
    assert result.execution_result.status == ExecutionStatus.NOT_RUN
    assert "Not a coding request" in result.explanation
    assert dependencies.llm.tool_bound_calls == 0
    assert len(dependencies.llm.calls) == 1  # only the plan call
    assert not any(workspace.iterdir())


@pytest.mark.parametrize(
    "bad_decision",
    [
        {"steps": [], "is_coding_task": True},
        {"steps": ["Rejected"], "is_coding_task": False},
    ],
)
def test_invalid_plan_decision_is_a_service_error(make_dependencies, workspace, bad_decision):
    dependencies = make_dependencies(structured=[bad_decision])
    with pytest.raises(LLMServiceError):
        run_coder_agent("Write something", workspace, dependencies=dependencies)
