"""Builds the prompt for every LLM call, retrieving long-term memory first (research R4).

Used by both agents: ``build_llm_messages`` for the Coder agent and ``build_pm_messages`` for the
PM agent. Both retrieve memory through ``retrieve_past_context`` (002 research R9).
"""

import logging

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage

from agents.dependencies import AgentDependencies
from agents.prompts import (
    PAST_CONTEXT_TEMPLATE,
    PM_SYSTEM_PROMPT,
    REQUIREMENT_TEMPLATE,
    SYSTEM_PROMPT,
    TASK_TEMPLATE,
)
from agents.state import CoderState
from orchestration.state import TeamState

logger = logging.getLogger(__name__)


def build_llm_messages(
    state: CoderState,
    instruction: str,
    dependencies: AgentDependencies,
    include_conversation: bool = True,
) -> list[BaseMessage]:
    """Return the full message list for one LLM call.

    Every node that calls the model goes through this function, so long-term memory is
    retrieved before every call. The result contains, in order: the system prompt, any relevant
    past context, the task and plan, the windowed ReAct conversation (unless
    ``include_conversation`` is False, which calls without bound tools need, because the API
    rejects tool-call history when no tools are defined), and ``instruction``.
    """
    system_text = _with_past_context(
        SYSTEM_PROMPT, retrieve_past_context(_retrieval_query(state), dependencies)
    )

    plan = "\n".join(
        f"{number}. {step}" for number, step in enumerate(state.get("plan_steps", []), 1)
    )
    task_message = HumanMessage(
        TASK_TEMPLATE.format(task=state["task"], plan=plan or "(not planned yet)")
    )
    conversation = (
        dependencies.buffer.window(state.get("messages", [])) if include_conversation else []
    )
    return [SystemMessage(system_text), task_message, *conversation, HumanMessage(instruction)]


def build_pm_messages(
    state: TeamState, instruction: str, dependencies: AgentDependencies
) -> list[BaseMessage]:
    """Return the full message list for one PM agent model call.

    Retrieves long-term memory for the requirement first (spec FR-015), then returns, in order:
    the PM system prompt with any relevant past context, the requirement, and ``instruction``.
    """
    past_context = retrieve_past_context(state["requirement"], dependencies)
    return [
        SystemMessage(_with_past_context(PM_SYSTEM_PROMPT, past_context)),
        HumanMessage(REQUIREMENT_TEMPLATE.format(requirement=state["requirement"])),
        HumanMessage(instruction),
    ]


def retrieve_past_context(query: str, dependencies: AgentDependencies) -> list[str]:
    """Return the long-term memory records relevant to ``query`` (the one retrieval path)."""
    settings = dependencies.settings
    past_context = dependencies.memory.retrieve(
        query, settings.memory_top_k, settings.memory_max_distance
    )
    logger.debug("Retrieved %d past-context records: %s", len(past_context), past_context)
    return past_context


def _with_past_context(system_prompt: str, past_context: list[str]) -> str:
    """Append the past-context section to ``system_prompt`` when there is any."""
    if not past_context:
        return system_prompt
    items = "\n".join(f"- {item}" for item in past_context)
    return system_prompt + "\n" + PAST_CONTEXT_TEMPLATE.format(items=items)


def _retrieval_query(state: CoderState) -> str:
    """Use the task plus the latest observation as the memory search query."""
    latest_observation = next(
        (
            str(message.content)
            for message in reversed(state.get("messages", []))
            if isinstance(message, ToolMessage)
        ),
        "",
    )
    return f"{state['task']}\n{latest_observation}".strip()
