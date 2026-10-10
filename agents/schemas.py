"""Structured output models for the Coder agent (constitution Principle II).

See specs/001-coder-agent/data-model.md for the field rules these models enforce.
"""

from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from config import MAX_ITERATIONS, MAX_REVISIONS


class _StrictModel(BaseModel):
    """Base model that rejects unknown fields."""

    model_config = ConfigDict(extra="forbid")


class ExecutionStatus(StrEnum):
    """Outcome of running the generated code."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    NOT_RUN = "not_run"


class StopReason(StrEnum):
    """Why the agent stopped working on a task."""

    COMPLETED = "completed"
    ITERATION_LIMIT = "iteration_limit"
    REVISION_LIMIT = "revision_limit"
    REJECTED = "rejected"


class GeneratedFile(_StrictModel):
    """A file in the task workspace when the agent finished."""

    path: str
    content: str

    @field_validator("path")
    @classmethod
    def _path_is_relative_inside_workspace(cls, path: str) -> str:
        pure = PurePosixPath(path)
        if not path or pure.is_absolute() or ".." in pure.parts:
            raise ValueError(f"path must be relative and inside the workspace: {path!r}")
        return path


class ReActStep(_StrictModel):
    """One Thought -> Action -> Observation step."""

    iteration: int = Field(ge=1)
    thought: str
    action: str | None = None
    action_input: dict[str, Any] = Field(default_factory=dict)
    observation: str | None = None


class ExecutionResult(_StrictModel):
    """Outcome of running the generated code."""

    status: ExecutionStatus
    success: bool
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    truncated: bool = False
    duration_seconds: float | None = None
    entrypoint: str | None = None

    @model_validator(mode="after")
    def _fields_agree_with_status(self) -> Self:
        if self.success != (self.status == ExecutionStatus.SUCCEEDED):
            raise ValueError("success must be true exactly when status is 'succeeded'")
        no_exit_code = (ExecutionStatus.TIMED_OUT, ExecutionStatus.NOT_RUN)
        if self.status in no_exit_code and self.exit_code is not None:
            raise ValueError(f"exit_code must be None when status is '{self.status}'")
        return self

    @classmethod
    def not_run(cls) -> "ExecutionResult":
        """Result for a task whose code was never run."""
        return cls(status=ExecutionStatus.NOT_RUN, success=False)


class ExecutionPlan(_StrictModel):
    """The plan made before coding and the trace of what the agent actually did."""

    steps: list[str] = Field(min_length=1)
    trace: list[ReActStep] = Field(default_factory=list)
    iterations: int = Field(ge=0, le=MAX_ITERATIONS)
    revision_attempts: int = Field(ge=0, le=MAX_REVISIONS)
    stop_reason: StopReason


class CoderResult(_StrictModel):
    """The single structured result the Coder agent returns (spec FR-007)."""

    code: list[GeneratedFile]
    explanation: str
    plan: ExecutionPlan
    execution_result: ExecutionResult

    @field_validator("explanation")
    @classmethod
    def _explanation_not_blank(cls, explanation: str) -> str:
        if not explanation.strip():
            raise ValueError("explanation must not be blank")
        return explanation

    @model_validator(mode="after")
    def _rejected_results_have_no_code(self) -> Self:
        if self.plan.stop_reason == StopReason.REJECTED:
            if self.code:
                raise ValueError("a rejected task must not return code")
            if self.execution_result.status != ExecutionStatus.NOT_RUN:
                raise ValueError("a rejected task must have execution_result.status 'not_run'")
        return self


class PlanDecision(_StrictModel):
    """Structured output of the planning LLM call."""

    steps: list[str] = Field(min_length=1, description="Ordered steps to complete the task.")
    is_coding_task: bool = Field(description="True if the task asks for a program or script.")
    rejection_reason: str | None = Field(
        default=None, description="Why the task was rejected; required when not a coding task."
    )

    @model_validator(mode="after")
    def _rejection_needs_reason(self) -> Self:
        if not self.is_coding_task and not (self.rejection_reason or "").strip():
            raise ValueError("rejection_reason is required when is_coding_task is false")
        return self


class ExplanationDraft(_StrictModel):
    """Structured output of the explanation LLM call."""

    explanation: str = Field(description="What the code does and how to run it.")

    @field_validator("explanation")
    @classmethod
    def _explanation_not_blank(cls, explanation: str) -> str:
        if not explanation.strip():
            raise ValueError("explanation must not be blank")
        return explanation
