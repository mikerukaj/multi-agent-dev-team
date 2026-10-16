"""The PM agent: turns a requirement into a technical specification and an ordered task list.

Its nodes run inside the team graph (orchestration/team_graph.py) and write to the shared
``TeamState`` (specs/002-pm-agent/research.md R5–R7, R9).
"""

import json
import logging

from langchain_core.runnables import Runnable
from pydantic import ValidationError

from agents.context import build_pm_messages
from agents.dependencies import AgentDependencies
from agents.errors import LLMServiceError
from agents.llm import invoke_model
from agents.prompts import CONSOLIDATE_PROMPT, SPECIFY_PROMPT
from config import MAX_TASKS
from memory.semantic_memory import MemoryRecord
from orchestration.protocol import (
    SpecificationDraft,
    TaskListDraft,
    TaskRecord,
    TechnicalSpecification,
)
from orchestration.state import TeamState

logger = logging.getLogger(__name__)

STRUCTURED_OUTPUT_METHOD = "json_schema"
"""Native structured output; Sonnet 5.5 rejects the forced tool call LangChain uses by default."""


class PMNodes:
    """The PM agent's graph nodes. Each returns a partial ``TeamState`` update."""

    def __init__(self, dependencies: AgentDependencies) -> None:
        self.dependencies = dependencies

    def specify(self, state: TeamState) -> TeamState:
        """Write the specification and its tasks (all ``not_started``) into shared state.

        A declined requirement writes ``decline_reason`` and no specification or tasks.
        """
        messages = build_pm_messages(state, SPECIFY_PROMPT, self.dependencies)
        draft: SpecificationDraft = invoke_model(
            self._structured(SpecificationDraft), messages, "PM specify"
        )
        requirement_record = MemoryRecord(
            kind="requirement", text=state["requirement"], run_id=state["run_id"]
        )
        if draft.specification is None:
            logger.info("PM: declined: %s", draft.decline_reason)
            self.dependencies.memory.add([requirement_record])
            return {
                "specification": None,
                "tasks": [],
                "decline_reason": draft.decline_reason,
                "consolidation_attempts": 0,
            }
        specification = draft.specification
        logger.info(
            "PM: specification '%s' with %d tasks", specification.name, len(specification.tasks)
        )
        self.dependencies.memory.add(
            [requirement_record, _specification_record(specification, state["run_id"])]
        )
        return {
            "specification": specification,
            "tasks": [TaskRecord(task=task) for task in specification.tasks],
            "decline_reason": None,
            "consolidation_attempts": 0,
        }

    def consolidate(self, state: TeamState) -> TeamState:
        """Merge an over-long task list into at most ``MAX_TASKS`` tasks (spec FR-004a)."""
        specification = state["specification"]
        instruction = CONSOLIDATE_PROMPT.format(
            task_count=len(specification.tasks),
            max_tasks=MAX_TASKS,
            tasks_json=json.dumps([task.model_dump(mode="json") for task in specification.tasks]),
        )
        messages = build_pm_messages(state, instruction, self.dependencies)
        draft: TaskListDraft = invoke_model(
            self._structured(TaskListDraft), messages, "PM consolidate"
        )
        try:
            merged = TechnicalSpecification.model_validate(
                {**specification.model_dump(), "tasks": [t.model_dump() for t in draft.tasks]}
            )
        except ValidationError as error:
            raise LLMServiceError(f"PM consolidate failed: {error}") from error
        attempts = state.get("consolidation_attempts", 0) + 1
        logger.info("PM: consolidated to %d tasks (attempt %d)", len(merged.tasks), attempts)
        self.dependencies.memory.add([_specification_record(merged, state["run_id"])])
        return {
            "specification": merged,
            "tasks": [TaskRecord(task=task) for task in merged.tasks],
            "consolidation_attempts": attempts,
        }

    def _structured(self, schema: type) -> Runnable:
        return self.dependencies.llm.with_structured_output(schema, method=STRUCTURED_OUTPUT_METHOD)


def _specification_record(specification: TechnicalSpecification, run_id: str) -> MemoryRecord:
    """A memory record with the spec's name, description and task titles (research R9)."""
    tasks = "\n".join(f"{task.id}: {task.title}" for task in specification.tasks)
    text = f"Specification: {specification.name}\n{specification.description}\nTasks:\n{tasks}"
    return MemoryRecord(kind="specification", text=text, run_id=run_id)
