"""Smoke test: the real PM and Coder agents on the Los Angeles date/time requirement.

Constitution Principle III and spec FR-014. Calls the real Anthropic API.
"""

import os

import pytest
from dotenv import load_dotenv

from agents.dependencies import AgentDependencies
from orchestration.protocol import OutcomeStatus, TaskStatus, TeamResult
from orchestration.team_graph import run_dev_team
from tests.integration.test_smoke_coder_agent import DATE_PATTERN, TIME_PATTERN

load_dotenv()  # so a key kept in .env is seen by the skip check below

SMOKE_REQUIREMENT = (
    "Build a command-line application that displays the current date and time in Los Angeles, "
    "California"
)


@pytest.mark.smoke
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY", "").strip(), reason="ANTHROPIC_API_KEY not set"
)
def test_smoke_team(settings, workspace):
    # Explicit dependencies keep this test on the temporary Chroma folder (spec FR-012a of 001).
    dependencies = AgentDependencies.from_settings(settings)

    result = run_dev_team(SMOKE_REQUIREMENT, workspace=workspace, dependencies=dependencies)

    assert isinstance(result, TeamResult)
    assert result.specification is not None
    assert result.specification.requirements and result.specification.tasks
    for record in result.tasks:
        assert record.status == TaskStatus.COMPLETED, record.report
        assert record.handoff is not None and record.report is not None
    assert result.code and all(file.content.strip() for file in result.code)
    assert result.outcome.status == OutcomeStatus.COMPLETED, result.outcome.reason

    run = result.execution_result
    assert run.success is True, run.stderr
    assert DATE_PATTERN.search(run.stdout), run.stdout
    assert TIME_PATTERN.search(run.stdout), run.stdout
