"""Validation rules of the structured output models (data-model.md)."""

import pytest
from pydantic import ValidationError

from agents.schemas import (
    CoderResult,
    ExecutionPlan,
    ExecutionResult,
    GeneratedFile,
    PlanDecision,
    StopReason,
)


def _valid_result(**overrides) -> dict:
    result = {
        "code": [{"path": "main.py", "content": "print('hi')"}],
        "explanation": "Prints hi. Run with `python main.py`.",
        "plan": {
            "steps": ["Write main.py", "Run it"],
            "trace": [{"iteration": 1, "thought": "Write it", "action": "write_file"}],
            "iterations": 2,
            "revision_attempts": 0,
            "stop_reason": "completed",
        },
        "execution_result": {
            "status": "succeeded",
            "success": True,
            "exit_code": 0,
            "stdout": "hi\n",
        },
    }
    result.update(overrides)
    return result


def test_valid_result_round_trips_through_json():
    result = CoderResult.model_validate(_valid_result())
    assert CoderResult.model_validate(result.model_dump(mode="json")) == result


def test_extra_top_level_field_is_rejected():
    with pytest.raises(ValidationError):
        CoderResult.model_validate(_valid_result(extra="nope"))


def test_blank_explanation_is_rejected():
    with pytest.raises(ValidationError):
        CoderResult.model_validate(_valid_result(explanation="   "))


def test_success_must_match_status():
    with pytest.raises(ValidationError):
        ExecutionResult(status="failed", success=True, exit_code=1)


def test_timed_out_has_no_exit_code():
    with pytest.raises(ValidationError):
        ExecutionResult(status="timed_out", success=False, exit_code=0)


@pytest.mark.parametrize("path", ["../escape.py", "/etc/passwd", "a/../../b.py", ""])
def test_generated_file_path_must_stay_inside_workspace(path):
    with pytest.raises(ValidationError):
        GeneratedFile(path=path, content="")


@pytest.mark.parametrize(
    ("field", "value"), [("iterations", 11), ("revision_attempts", 4), ("steps", [])]
)
def test_plan_bounds(field, value):
    plan = {"steps": ["a"], "iterations": 1, "revision_attempts": 0, "stop_reason": "completed"}
    plan[field] = value
    with pytest.raises(ValidationError):
        ExecutionPlan.model_validate(plan)


def test_rejected_result_must_have_no_code():
    rejected_plan = {
        "steps": ["Rejected: not code"],
        "iterations": 0,
        "revision_attempts": 0,
        "stop_reason": StopReason.REJECTED,
    }
    with pytest.raises(ValidationError):
        CoderResult.model_validate(
            _valid_result(plan=rejected_plan, execution_result=ExecutionResult.not_run())
        )


def test_plan_decision_needs_steps_and_rejection_reason():
    with pytest.raises(ValidationError):
        PlanDecision(steps=[], is_coding_task=True)
    with pytest.raises(ValidationError):
        PlanDecision(steps=["Rejected"], is_coding_task=False)
    assert PlanDecision(steps=["x"], is_coding_task=False, rejection_reason="Not code")
