"""LangGraph state shared by the PM agent and the Coder agent (data-model.md › TeamState)."""

from typing import TypedDict

from agents.schemas import ExecutionResult, GeneratedFile
from orchestration.protocol import (
    TaskHandoff,
    TaskRecord,
    TaskReport,
    TeamResult,
    TechnicalSpecification,
)


class TeamState(TypedDict, total=False):
    """Everything both agents read and write while working on one requirement.

    A non-empty ``current_handoff`` is the signal that a task is ready for the Coder agent
    (contracts/handoff-protocol.md). ``tasks`` holds every task with its status, handoff and
    report; ``code`` is the shared workspace's files after the latest task.
    """

    run_id: str
    requirement: str
    specification: TechnicalSpecification | None
    decline_reason: str | None
    consolidation_attempts: int
    tasks: list[TaskRecord]
    current_handoff: TaskHandoff | None
    last_report: TaskReport | None
    code: list[GeneratedFile]
    final_execution: ExecutionResult | None
    result: TeamResult
