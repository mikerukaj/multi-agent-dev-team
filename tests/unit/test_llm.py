"""The shared model-call helper (research R10, constitution Principle I)."""

import pytest
from langchain_core.runnables import RunnableLambda

from agents.errors import InvalidTaskError, LLMServiceError
from agents.llm import invoke_model


def _raise(error: Exception):
    def run(_payload):
        raise error

    return RunnableLambda(run)


def test_returns_the_runnable_output():
    assert invoke_model(RunnableLambda(lambda payload: payload * 2), 21) == 42


def test_other_errors_become_service_errors_with_the_stage():
    with pytest.raises(LLMServiceError, match=r"^PM specify failed: boom"):
        invoke_model(_raise(RuntimeError("boom")), None, "PM specify")


def test_default_stage_keeps_the_original_message():
    with pytest.raises(LLMServiceError, match=r"^Model call failed: boom"):
        invoke_model(_raise(RuntimeError("boom")), None)


def test_agent_errors_pass_through_unchanged():
    with pytest.raises(InvalidTaskError, match=r"^inner$"):
        invoke_model(_raise(InvalidTaskError("inner")), None, "Task T1")
