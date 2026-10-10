"""Builds the prompt for every LLM call, retrieving long-term memory first (research R4)."""

import logging

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage

from agents.dependencies import AgentDependencies
from agents.prompts import PAST_CONTEXT_TEMPLATE, SYSTEM_PROMPT, TASK_TEMPLATE
from agents.state import CoderState

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
    settings = dependencies.settings
    past_context = dependencies.memory.retrieve(
        _retrieval_query(state), settings.memory_top_k, settings.memory_max_distance
    )
    logger.debug("Retrieved %d past-context records: %s", len(past_context), past_context)

    system_text = SYSTEM_PROMPT
    if past_context:
        items = "\n".join(f"- {item}" for item in past_context)
        system_text += "\n" + PAST_CONTEXT_TEMPLATE.format(items=items)

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
