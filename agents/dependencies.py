"""Everything the Coder agent needs at run time, grouped so it can be swapped in tests."""

import os
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel

from agents.errors import AgentConfigurationError
from config import CODER_MODEL, Settings
from memory.conversation_buffer import ConversationBuffer
from memory.semantic_memory import SemanticMemory


@dataclass(frozen=True)
class AgentDependencies:
    """The model, both memory layers and settings used by one agent run."""

    llm: BaseChatModel
    memory: SemanticMemory
    buffer: ConversationBuffer
    settings: Settings

    @classmethod
    def from_settings(cls, settings: Settings) -> "AgentDependencies":
        """Build the production dependencies: Opus 5.5, Chroma memory and the window buffer.

        Raises:
            AgentConfigurationError: if ANTHROPIC_API_KEY is not set or Chroma cannot be opened.
        """
        if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
            raise AgentConfigurationError(
                "ANTHROPIC_API_KEY is not set. Add it to your environment or .env file."
            )
        from langchain_anthropic import ChatAnthropic

        llm = ChatAnthropic(
            model=CODER_MODEL,
            max_tokens=settings.llm_max_tokens,
            max_retries=settings.llm_max_retries,
        )
        return cls(
            llm=llm,
            memory=SemanticMemory.from_settings(settings),
            buffer=ConversationBuffer(settings.memory_window_turns),
            settings=settings,
        )
