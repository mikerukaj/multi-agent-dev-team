"""The PM → Coder handoff protocol (spec US2, FR-005–FR-007, FR-010; handoff-protocol.md)."""

import pytest
from pydantic import ValidationError

from agents.schemas import (
    CoderResult,
    ExecutionPlan,
    ExecutionResult,
    ExecutionStatus,
    StopReason,
)
from orchestration.protocol import (
    TaskHandoff,
    TaskReport,
    TaskStatus,
    build_handoff,
    task_status_for,
)
from tests.conftest import make_specification


def _handoff() -> TaskHandoff:
    specification = make_specification(3)
    return build_handoff(specification, specification.tasks[1], "run1", ["clock.py"])


def _coder_result(execution: ExecutionResult, stop_reason: StopReason) -> CoderResult:
    rejected = stop_reason == StopReason.REJECTED
    return CoderResult(
        code=[] if rejected else [{"path": "main.py", "content": "print(1)"}],
        explanation="Explanation.",
        plan=ExecutionPlan(
            steps=["Step"], iterations=1, revision_attempts=0, stop_reason=stop_reason
        ),
        execution_result=execution,
    )


SUCCEEDED = ExecutionResult(status=ExecutionStatus.SUCCEEDED, success=True, exit_code=0)
FAILED = ExecutionResult(status=ExecutionStatus.FAILED, success=False, exit_code=1)
TIMED_OUT = ExecutionResult(status=ExecutionStatus.TIMED_OUT, success=False)
NOT_RUN = ExecutionResult.not_run()


def test_handoff_holds_only_the_covered_parts_of_the_spec():
    handoff = _handoff()
    assert handoff.task_id == "T2"
    assert [r.id for r in handoff.context.requirements] == ["R2"]
    assert [c.id for c in handoff.context.acceptance_criteria] == ["AC2"]
    assert handoff.context.out_of_scope == ["Other time zones."]
    assert handoff.priority == "high"
    assert handoff.depends_on == ["T1"]
    assert handoff.acceptance_criteria == ["Requirement 2 works."]
    assert handoff.workspace_files == ["clock.py"]
    assert handoff.protocol_version == "1"


def test_handoff_and_report_survive_a_json_round_trip():
    handoff = _handoff()
    assert TaskHandoff.model_validate_json(handoff.model_dump_json()) == handoff

    report = TaskReport(
        task_id="T2",
        status=TaskStatus.COMPLETED,
        coder_result=_coder_result(SUCCEEDED, StopReason.COMPLETED),
    )
    assert TaskReport.model_validate_json(report.model_dump_json()) == report


@pytest.mark.parametrize(
    "change", [{"unexpected": "field"}, {"protocol_version": "2"}, {"priority": "urgent"}]
)
def test_handoff_rejects_unknown_fields_versions_and_priorities(change):
    data = {**_handoff().model_dump(mode="json"), **change}
    with pytest.raises(ValidationError):
        TaskHandoff.model_validate(data)


@pytest.mark.parametrize("status", [TaskStatus.NOT_STARTED, TaskStatus.IN_PROGRESS])
def test_report_status_must_be_finished(status):
    with pytest.raises(ValidationError, match="must be 'completed' or 'failed'"):
        TaskReport(
            task_id="T1", status=status, coder_result=_coder_result(SUCCEEDED, StopReason.COMPLETED)
        )


@pytest.mark.parametrize(
    ("execution", "stop_reason", "expected"),
    [
        (SUCCEEDED, StopReason.COMPLETED, TaskStatus.COMPLETED),
        (SUCCEEDED, StopReason.ITERATION_LIMIT, TaskStatus.COMPLETED),
        (NOT_RUN, StopReason.COMPLETED, TaskStatus.COMPLETED),
        (FAILED, StopReason.COMPLETED, TaskStatus.FAILED),
        (TIMED_OUT, StopReason.COMPLETED, TaskStatus.FAILED),
        (FAILED, StopReason.REVISION_LIMIT, TaskStatus.FAILED),
        (NOT_RUN, StopReason.ITERATION_LIMIT, TaskStatus.FAILED),
        (NOT_RUN, StopReason.REJECTED, TaskStatus.FAILED),
    ],
)
def test_task_status_rule(execution, stop_reason, expected):
    assert task_status_for(_coder_result(execution, stop_reason)) == expected
