"""LangGraph state for the Coder agent (see data-model.md › CoderState)."""

from typing import TypedDict

from langchain_core.messages import BaseMessage

from agents.schemas import ExecutionResult, ReActStep, StopReason


class CoderState(TypedDict, total=False):
    """Everything the graph nodes read and write while working on one task."""

    run_id: str
    task: str
    plan_steps: list[str]
    is_coding_task: bool
    rejection_reason: str | None
    messages: list[BaseMessage]
    trace: list[ReActStep]
    iteration: int
    first_failure_seen: bool
    revision_attempts: int
    last_execution: ExecutionResult | None
    files_changed_since_run: bool
    stop_reason: StopReason | None
