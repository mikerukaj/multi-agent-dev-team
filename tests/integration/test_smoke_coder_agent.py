"""Smoke test: the real agent on the Los Angeles date/time task.

Constitution Principle III and spec FR-012/FR-013. Calls the real Anthropic API.
"""

import os
import re

import pytest
from dotenv import load_dotenv

from agents.coder_agent import run_coder_agent
from agents.dependencies import AgentDependencies
from agents.schemas import CoderResult

load_dotenv()  # so a key kept in .env is seen by the skip check below

SMOKE_TASK = (
    "Write a python application that displays the current date and time in Los Angeles, California"
)
DATE_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)",
    re.IGNORECASE,
)
TIME_PATTERN = re.compile(r"\d{1,2}:\d{2}")


@pytest.mark.smoke
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY", "").strip(), reason="ANTHROPIC_API_KEY not set"
)
def test_smoke_coder_agent(settings, workspace):
    # Explicit dependencies keep this test on the temporary Chroma folder (spec FR-012a).
    dependencies = AgentDependencies.from_settings(settings)

    result = run_coder_agent(SMOKE_TASK, workspace=workspace, dependencies=dependencies)

    assert isinstance(result, CoderResult)
    assert result.code and all(file.content.strip() for file in result.code)
    assert result.explanation.strip()
    assert result.plan.steps
    assert result.execution_result is not None

    assert result.execution_result.success is True, result.execution_result.stderr
    assert DATE_PATTERN.search(result.execution_result.stdout), result.execution_result.stdout
    assert TIME_PATTERN.search(result.execution_result.stdout), result.execution_result.stdout
