"""The PM agent's specification and the PM → Coder handoff protocol (constitution Principle II).

See specs/002-pm-agent/data-model.md for the field rules these models enforce, and
contracts/handoff-protocol.md for the handoff lifecycle. Every model rejects unknown fields and
serializes to JSON with ``model_dump_json()``.
"""

from collections import Counter
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, field_validator, model_validator

from agents.schemas import (
    CoderResult,
    ExecutionResult,
    ExecutionStatus,
    GeneratedFile,
    StopReason,
    _StrictModel,
)

PROTOCOL_VERSION = "1"
"""Version of the TaskHandoff / TaskReport messages. Bump on any breaking change."""


class TaskPriority(StrEnum):
    """How important a task is. Tasks are still handed off in list order."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TaskStatus(StrEnum):
    """Where a task is in its life cycle."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class OutcomeStatus(StrEnum):
    """The overall result of one requirement."""

    COMPLETED = "completed"
    FAILED = "failed"
    DECLINED = "declined"


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


NonBlankStr = Annotated[str, AfterValidator(_not_blank)]
"""A string that must contain more than whitespace."""


def _duplicates(ids: list[str]) -> list[str]:
    return sorted(identifier for identifier, count in Counter(ids).items() if count > 1)


class Requirement(_StrictModel):
    """One functional requirement of the specification."""

    id: str = Field(pattern=r"^R\d+$", description="Requirement ID: R1, R2, ...")
    statement: NonBlankStr = Field(
        description="One testable statement of what the program MUST do."
    )


class AcceptanceCriterion(_StrictModel):
    """A checkable condition that shows one requirement is met."""

    id: str = Field(pattern=r"^AC\d+$", description="Acceptance criterion ID: AC1, AC2, ...")
    requirement_id: str = Field(description="ID of the requirement this criterion checks.")
    text: NonBlankStr = Field(description="The condition, checkable by running the program.")


class PlannedTask(_StrictModel):
    """One discrete unit of work the Coder agent can complete in a single handoff."""

    id: str = Field(pattern=r"^T\d+$", description="Task ID: T1, T2, ... in execution order.")
    title: NonBlankStr = Field(description="Short name of the task.")
    description: NonBlankStr = Field(
        description="What Python code to write or change in this task."
    )
    acceptance_criteria: list[str] = Field(
        min_length=1, description="Conditions that show this task is done."
    )
    priority: TaskPriority = Field(description="How important the task is: high, medium or low.")
    covers: list[str] = Field(
        min_length=1, description="IDs of the requirements this task delivers."
    )
    depends_on: list[str] = Field(
        default_factory=list, description="IDs of earlier tasks this task builds on."
    )


class TechnicalSpecification(_StrictModel):
    """The PM agent's formal specification, including its ordered task list (spec FR-002)."""

    name: NonBlankStr = Field(description="Short name of the program being built.")
    description: NonBlankStr = Field(
        description="What the program is and who it is for, 1-3 sentences."
    )
    requirements: list[Requirement] = Field(min_length=1, description="Functional requirements.")
    acceptance_criteria: list[AcceptanceCriterion] = Field(
        min_length=1, description="At least one criterion per requirement."
    )
    assumptions: list[str] = Field(default_factory=list, description="Assumptions made.")
    out_of_scope: list[str] = Field(default_factory=list, description="What is not built.")
    tasks: list[PlannedTask] = Field(
        min_length=1, description="Ordered tasks; together they cover every requirement."
    )

    @model_validator(mode="after")
    def _ids_and_links_are_consistent(self) -> Self:
        """Enforce spec FR-004. The task count is deliberately not checked (research R6)."""
        requirement_ids = [requirement.id for requirement in self.requirements]
        for label, ids in (
            ("requirement", requirement_ids),
            ("acceptance criterion", [criterion.id for criterion in self.acceptance_criteria]),
            ("task", [task.id for task in self.tasks]),
        ):
            if duplicates := _duplicates(ids):
                raise ValueError(f"duplicate {label} IDs: {', '.join(duplicates)}")
        known_requirements = set(requirement_ids)
        for criterion in self.acceptance_criteria:
            if criterion.requirement_id not in known_requirements:
                raise ValueError(
                    f"acceptance criterion {criterion.id} names unknown requirement "
                    f"{criterion.requirement_id}"
                )
        self._check_tasks(known_requirements)
        return self

    def _check_tasks(self, known_requirements: set[str]) -> None:
        earlier_tasks: set[str] = set()
        covered: set[str] = set()
        all_task_ids = {task.id for task in self.tasks}
        for task in self.tasks:
            if unknown := sorted(set(task.covers) - known_requirements):
                raise ValueError(
                    f"task {task.id} covers unknown requirements: {', '.join(unknown)}"
                )
            for dependency in task.depends_on:
                if dependency not in earlier_tasks:
                    kind = (
                        "itself"
                        if dependency == task.id
                        else ("a later task" if dependency in all_task_ids else "an unknown task")
                    )
                    raise ValueError(f"task {task.id} depends on {kind}: {dependency}")
            earlier_tasks.add(task.id)
            covered.update(task.covers)
        if uncovered := sorted(known_requirements - covered):
            raise ValueError(f"requirements not covered by any task: {', '.join(uncovered)}")


class SpecificationDraft(_StrictModel):
    """Structured output of the PM agent's ``specify`` model call."""

    is_software_requirement: bool = Field(
        description="True only for a software request that can be built as a standard-library "
        "Python program."
    )
    decline_reason: str | None = Field(
        default=None, description="Why the request is declined; required when declining."
    )
    specification: TechnicalSpecification | None = Field(
        default=None, description="The specification; required when not declining."
    )

    @model_validator(mode="after")
    def _decline_xor_specification(self) -> Self:
        if self.is_software_requirement:
            if self.specification is None:
                raise ValueError("specification is required when the requirement is accepted")
        else:
            if not (self.decline_reason or "").strip():
                raise ValueError("decline_reason is required when the requirement is declined")
            if self.specification is not None:
                raise ValueError("a declined requirement must not have a specification")
        return self


class TaskListDraft(_StrictModel):
    """Structured output of the PM agent's ``consolidate`` model call."""

    tasks: list[PlannedTask] = Field(
        min_length=1, description="The merged, ordered task list that replaces the old one."
    )


class SpecificationContext(_StrictModel):
    """The parts of the specification a task needs: never the requirements it doesn't cover."""

    name: str
    description: str
    out_of_scope: list[str]
    requirements: list[Requirement]
    acceptance_criteria: list[AcceptanceCriterion]


class TaskHandoff(_StrictModel):
    """PM side → Coder agent: one task is ready (contracts/handoff-protocol.md)."""

    protocol_version: Literal["1"] = PROTOCOL_VERSION
    run_id: str
    task_id: str
    title: str
    description: str
    acceptance_criteria: list[str] = Field(min_length=1)
    priority: TaskPriority
    depends_on: list[str]
    context: SpecificationContext
    workspace_files: list[str]


class TaskReport(_StrictModel):
    """Coder agent → shared state: the outcome of one handed-off task."""

    protocol_version: Literal["1"] = PROTOCOL_VERSION
    task_id: str
    status: TaskStatus
    coder_result: CoderResult

    @field_validator("status")
    @classmethod
    def _finished_status_only(cls, status: TaskStatus) -> TaskStatus:
        if status not in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            raise ValueError("a report's status must be 'completed' or 'failed'")
        return status


class TaskRecord(_StrictModel):
    """One task in the shared state, with its status, handoff and report."""

    task: PlannedTask
    status: TaskStatus = TaskStatus.NOT_STARTED
    handoff: TaskHandoff | None = None
    report: TaskReport | None = None

    @model_validator(mode="after")
    def _status_matches_messages(self) -> Self:
        finished = self.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
        if finished and self.report is None:
            raise ValueError(f"a {self.status} task needs a report")
        if self.status != TaskStatus.NOT_STARTED and self.handoff is None:
            raise ValueError(f"a {self.status} task needs a handoff")
        return self


class TeamOutcome(_StrictModel):
    """Whether the requirement was completed, failed or declined, and why."""

    status: OutcomeStatus
    reason: NonBlankStr


class TeamResult(_StrictModel):
    """The single structured result of the two-agent system (spec FR-011)."""

    specification: TechnicalSpecification | None
    tasks: list[TaskRecord]
    code: list[GeneratedFile]
    execution_result: ExecutionResult
    outcome: TeamOutcome

    @model_validator(mode="after")
    def _outcome_matches_facts(self) -> Self:
        status = self.outcome.status
        run_failed = self.execution_result.status in (
            ExecutionStatus.FAILED,
            ExecutionStatus.TIMED_OUT,
        )
        any_task_failed = any(record.status == TaskStatus.FAILED for record in self.tasks)
        if status == OutcomeStatus.DECLINED:
            if self.specification is not None or self.tasks or self.code:
                raise ValueError("a declined result has no specification, tasks or code")
            if self.execution_result.status != ExecutionStatus.NOT_RUN:
                raise ValueError("a declined result's execution_result must be 'not_run'")
        elif self.specification is None or not self.tasks:
            raise ValueError(f"a {status} result needs a specification and tasks")
        elif status == OutcomeStatus.COMPLETED:
            all_done = all(record.status == TaskStatus.COMPLETED for record in self.tasks)
            if not all_done or run_failed:
                raise ValueError(
                    "'completed' needs every task completed and a final run that did not fail"
                )
        elif not (any_task_failed or run_failed):
            raise ValueError("'failed' needs a failed task or a failed final run")
        return self


def build_handoff(
    specification: TechnicalSpecification,
    task: PlannedTask,
    run_id: str,
    workspace_files: list[str],
) -> TaskHandoff:
    """Build the handoff for ``task``: its fields plus only the spec parts it covers (FR-005)."""
    covered = set(task.covers)
    return TaskHandoff(
        run_id=run_id,
        task_id=task.id,
        title=task.title,
        description=task.description,
        acceptance_criteria=task.acceptance_criteria,
        priority=task.priority,
        depends_on=task.depends_on,
        context=SpecificationContext(
            name=specification.name,
            description=specification.description,
            out_of_scope=specification.out_of_scope,
            requirements=[r for r in specification.requirements if r.id in covered],
            acceptance_criteria=[
                c for c in specification.acceptance_criteria if c.requirement_id in covered
            ],
        ),
        workspace_files=workspace_files,
    )


def task_status_for(result: CoderResult) -> TaskStatus:
    """Completed or failed, from the Coder agent's result (spec FR-010, handoff-protocol.md).

    Completed when the run succeeded, or when nothing was run and the Coder agent finished
    normally. Anything else (a failed or timed-out run, a round or revision limit, or a rejected
    task) is failed.
    """
    if result.execution_result.success:
        return TaskStatus.COMPLETED
    finished_without_run = (
        result.execution_result.status == ExecutionStatus.NOT_RUN
        and result.plan.stop_reason == StopReason.COMPLETED
    )
    return TaskStatus.COMPLETED if finished_without_run else TaskStatus.FAILED
