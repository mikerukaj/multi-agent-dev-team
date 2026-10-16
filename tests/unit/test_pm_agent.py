"""The PM agent's nodes and the consolidation loop (spec US1, FR-002–FR-004a, FR-015)."""

import pytest
from pydantic import ValidationError

from agents.errors import LLMServiceError, TaskPlanningError
from agents.pm_agent import PMNodes
from agents.prompts import SPECIFY_PROMPT
from config import MAX_CONSOLIDATION_ATTEMPTS, MAX_TASKS
from orchestration.protocol import (
    PlannedTask,
    SpecificationDraft,
    TaskListDraft,
    TaskRecord,
    TaskStatus,
    TechnicalSpecification,
)
from orchestration.team_graph import route_after_planning
from tests.conftest import make_specification

REQUIREMENT = "Build an LA clock"


def _planned_state(task_count: int, attempts: int = 0) -> dict:
    specification = make_specification(task_count)
    return {
        "run_id": "r1",
        "requirement": REQUIREMENT,
        "specification": specification,
        "decline_reason": None,
        "tasks": [TaskRecord(task=task) for task in specification.tasks],
        "consolidation_attempts": attempts,
    }


def _merged_tasks(requirement_count: int, task_count: int) -> TaskListDraft:
    """``task_count`` tasks covering R1..R<requirement_count>; T1 takes the extra requirements."""
    extra = requirement_count - task_count
    tasks = []
    for number in range(1, task_count + 1):
        first = 1 if number == 1 else number + extra
        last = 1 + extra if number == 1 else number + extra
        tasks.append(
            PlannedTask(
                id=f"T{number}",
                title=f"Merged task {number}",
                description="Write the merged code.",
                acceptance_criteria=["It works."],
                priority="medium",
                covers=[f"R{n}" for n in range(first, last + 1)],
                depends_on=[f"T{number - 1}"] if number > 1 else [],
            )
        )
    return TaskListDraft(tasks=tasks)


def test_specify_writes_non_empty_task_list_to_shared_state(make_dependencies, specification_draft):
    pm = PMNodes(make_dependencies(structured=[specification_draft]))

    update = pm.specify({"run_id": "r1", "requirement": REQUIREMENT})

    specification = TechnicalSpecification.model_validate(update["specification"].model_dump())
    assert update["tasks"], "the PM node must write a non-empty task list"
    for record, planned in zip(update["tasks"], specification.tasks, strict=True):
        assert TaskRecord.model_validate(record.model_dump()) == record
        assert record.status == TaskStatus.NOT_STARTED
        assert record.task.id == planned.id
        assert record.handoff is None and record.report is None
    assert update["consolidation_attempts"] == 0
    assert update["decline_reason"] is None


def test_specify_retrieves_memory_first(make_dependencies, specification_draft, retrieve_spy):
    PMNodes(make_dependencies(structured=[specification_draft])).specify(
        {"run_id": "r1", "requirement": REQUIREMENT}
    )
    assert retrieve_spy.calls == 1


def test_specify_stores_requirement_and_specification_records(
    make_dependencies, specification_draft, memory
):
    PMNodes(make_dependencies(structured=[specification_draft])).specify(
        {"run_id": "r1", "requirement": REQUIREMENT}
    )
    kinds = {record.kind for record in memory.recent(10) if record.run_id == "r1"}
    assert kinds == {"requirement", "specification"}


def test_consolidate_replaces_tasks_and_counts_the_attempt(make_dependencies):
    state = _planned_state(MAX_TASKS + 1)
    merged = _merged_tasks(MAX_TASKS + 1, MAX_TASKS)
    pm = PMNodes(make_dependencies(structured=[merged]))

    update = pm.consolidate(state)

    assert [record.task for record in update["tasks"]] == merged.tasks
    assert update["specification"].tasks == merged.tasks
    assert all(record.status == TaskStatus.NOT_STARTED for record in update["tasks"])
    assert update["consolidation_attempts"] == 1


def test_routing_consolidates_dispatches_or_gives_up():
    assert route_after_planning(_planned_state(MAX_TASKS + 1)) == "consolidate"
    assert route_after_planning(_planned_state(MAX_TASKS)) == "dispatch_task"
    with pytest.raises(TaskPlanningError):
        route_after_planning(_planned_state(MAX_TASKS + 1, attempts=MAX_CONSOLIDATION_ATTEMPTS))


def test_consolidation_that_drops_a_requirement_is_a_service_error(make_dependencies):
    state = _planned_state(MAX_TASKS + 1)
    incomplete = _merged_tasks(MAX_TASKS, MAX_TASKS)  # covers R1..R8, so R9 is uncovered
    pm = PMNodes(make_dependencies(structured=[incomplete]))
    with pytest.raises(LLMServiceError, match=r"(?s)^PM consolidate failed:.*R9"):
        pm.consolidate(state)


def test_unparseable_consolidation_answer_names_the_stage(make_dependencies):
    pm = PMNodes(make_dependencies(structured=[{"not_tasks": []}]))
    with pytest.raises(LLMServiceError, match=r"^PM consolidate failed:"):
        pm.consolidate(_planned_state(MAX_TASKS + 1))


def test_specify_declines_with_a_reason_and_no_tasks(make_dependencies, memory):
    declined = SpecificationDraft(is_software_requirement=False, decline_reason="Not software")
    pm = PMNodes(make_dependencies(structured=[declined]))

    update = pm.specify({"run_id": "r1", "requirement": "What is the capital of France?"})

    assert update["decline_reason"] == "Not software"
    assert update["specification"] is None
    assert update["tasks"] == []
    assert {record.kind for record in memory.recent(10)} == {"requirement"}


def test_declined_draft_needs_a_reason():
    with pytest.raises(ValidationError, match="decline_reason is required"):
        SpecificationDraft(is_software_requirement=False)


def test_specify_prompt_keeps_the_standard_library_python_decline_rule():
    # Spec FR-012 and US3 scenario 4: software that can't be built is declined, never swapped.
    assert "standard-library" in SPECIFY_PROMPT and "Python" in SPECIFY_PROMPT
    assert "Never" in SPECIFY_PROMPT and "substitute" in SPECIFY_PROMPT
