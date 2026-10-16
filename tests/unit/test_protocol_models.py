"""Specification and task-list validation rules (spec FR-004, edge cases; research R7)."""

from collections.abc import Callable

import pytest
from pydantic import ValidationError

from orchestration.protocol import SpecificationDraft, TechnicalSpecification
from tests.conftest import make_specification


def _broken(change: Callable[[dict], None]) -> dict:
    """A valid three-task spec as a dict, with one thing changed."""
    data = make_specification(3).model_dump()
    change(data)
    return data


def _set(path: list, value) -> Callable[[dict], None]:
    def change(data: dict) -> None:
        target = data
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return change


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (_set(["requirements", 1, "id"], "R1"), "duplicate requirement IDs: R1"),
        (_set(["acceptance_criteria", 1, "id"], "AC1"), "duplicate acceptance criterion IDs"),
        (_set(["tasks", 1, "id"], "T1"), "duplicate task IDs: T1"),
        (_set(["tasks", 1, "depends_on"], ["T2"]), "task T2 depends on itself: T2"),
        (_set(["tasks", 0, "depends_on"], ["T3"]), "task T1 depends on a later task: T3"),
        (_set(["tasks", 1, "depends_on"], ["T9"]), "task T2 depends on an unknown task: T9"),
        (_set(["tasks", 0, "covers"], ["R9"]), "task T1 covers unknown requirements: R9"),
        (_set(["tasks", 0, "covers"], []), "at least 1 item"),
        (_set(["acceptance_criteria", 0, "requirement_id"], "R9"), "names unknown requirement R9"),
        (_set(["tasks", 2, "covers"], ["R2"]), "requirements not covered by any task: R3"),
        (_set(["tasks"], []), "at least 1 item"),
        (_set(["requirements"], []), "at least 1 item"),
        (_set(["acceptance_criteria"], []), "at least 1 item"),
        (_set(["tasks", 0, "id"], "Task1"), "String should match pattern"),
        (_set(["requirements", 0, "id"], "Req1"), "String should match pattern"),
        (_set(["name"], "   "), "must not be blank"),
    ],
)
def test_invalid_specifications_are_rejected(change, message):
    with pytest.raises(ValidationError, match=message):
        TechnicalSpecification.model_validate(_broken(change))


def test_task_count_is_not_a_validation_rule():
    # Nine tasks validate: the count is handled by consolidation (research R6).
    assert len(make_specification(9).tasks) == 9


def test_accepted_draft_needs_a_specification():
    with pytest.raises(ValidationError, match="specification is required"):
        SpecificationDraft(is_software_requirement=True)


def test_declined_draft_must_not_have_a_specification():
    with pytest.raises(ValidationError, match="must not have a specification"):
        SpecificationDraft(
            is_software_requirement=False,
            decline_reason="Not software",
            specification=make_specification(),
        )
