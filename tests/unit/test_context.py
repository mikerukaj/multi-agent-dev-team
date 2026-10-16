"""Prompt building: memory retrieval before every LLM call (research R4)."""

import pytest
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from agents.context import build_llm_messages, build_pm_messages
from agents.dependencies import AgentDependencies
from agents.errors import AgentConfigurationError
from memory.semantic_memory import MemoryRecord


def _state(**overrides) -> dict:
    state = {
        "task": "Print the time in Los Angeles",
        "plan_steps": ["Write", "Run"],
        "messages": [],
    }
    state.update(overrides)
    return state


def test_retrieves_once_per_call(make_dependencies, retrieve_spy):
    dependencies = make_dependencies()
    build_llm_messages(_state(), "go", dependencies)
    build_llm_messages(_state(), "go", dependencies)
    assert retrieve_spy.calls == 2


def test_past_context_included_only_when_found(make_dependencies, memory):
    dependencies = make_dependencies()
    without = build_llm_messages(_state(), "go", dependencies)
    assert "Relevant past context" not in without[0].content

    memory.add([MemoryRecord(kind="result", text="Print the time in Los Angeles", run_id="old")])
    with_context = build_llm_messages(_state(), "go", dependencies)
    assert isinstance(with_context[0], SystemMessage)
    assert "Relevant past context" in with_context[0].content


def test_window_limits_conversation_and_task_is_always_present(make_dependencies):
    dependencies = make_dependencies()
    messages = []
    for number in range(10):
        call_id = f"call-{number}"
        messages.append(
            AIMessage(
                content=f"thought {number}",
                tool_calls=[{"name": "read_file", "args": {}, "id": call_id}],
            )
        )
        messages.append(ToolMessage(content=f"obs {number}", tool_call_id=call_id))

    prompt = build_llm_messages(_state(messages=messages), "go", dependencies)
    ai_messages = [m for m in prompt if isinstance(m, AIMessage)]
    assert len(ai_messages) == dependencies.settings.memory_window_turns
    assert "Print the time in Los Angeles" in prompt[1].content
    assert "1. Write" in prompt[1].content
    assert prompt[-1].content == "go"


def test_conversation_can_be_left_out(make_dependencies):
    messages = [AIMessage(content="t", tool_calls=[{"name": "read_file", "args": {}, "id": "1"}])]
    prompt = build_llm_messages(
        _state(messages=messages), "go", make_dependencies(), include_conversation=False
    )
    assert not any(isinstance(m, AIMessage) for m in prompt)


def test_from_settings_requires_api_key(settings, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(AgentConfigurationError, match="ANTHROPIC_API_KEY"):
        AgentDependencies.from_settings(settings)


PM_STATE = {"run_id": "r1", "requirement": "Build a clock for Los Angeles"}


def test_pm_messages_retrieve_memory_once(make_dependencies, retrieve_spy):
    build_pm_messages(PM_STATE, "Specify it.", make_dependencies())
    assert retrieve_spy.calls == 1


def test_pm_messages_hold_requirement_instruction_and_past_context(make_dependencies, memory):
    dependencies = make_dependencies()
    without = build_pm_messages(PM_STATE, "Specify it.", dependencies)
    assert "Relevant past context" not in without[0].content
    assert "Build a clock for Los Angeles" in without[1].content
    assert without[-1].content == "Specify it."

    memory.add([MemoryRecord(kind="specification", text="Clock for Los Angeles", run_id="old")])
    with_context = build_pm_messages(PM_STATE, "Specify it.", dependencies)
    assert isinstance(with_context[0], SystemMessage)
    assert "PM (product manager) agent" in with_context[0].content
    assert "Relevant past context" in with_context[0].content
