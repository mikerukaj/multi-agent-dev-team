"""Shared fixtures: temporary settings and memory, a fake embedder, and a scripted chat model."""

import hashlib
import math
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, Field

from agents.dependencies import AgentDependencies
from config import Settings
from memory.conversation_buffer import ConversationBuffer
from memory.semantic_memory import SemanticMemory
from orchestration.protocol import (
    AcceptanceCriterion,
    PlannedTask,
    Requirement,
    SpecificationDraft,
    TechnicalSpecification,
)

EMBEDDING_DIMENSIONS = 64


class HashEmbedding(EmbeddingFunction[Documents]):
    """Deterministic bag-of-words embedding, so tests need no model download."""

    def __init__(self) -> None:
        pass

    def __call__(self, input: Documents) -> Embeddings:  # noqa: A002 (Chroma's parameter name)
        return [self._embed(text) for text in input]

    @staticmethod
    def name() -> str:
        return "test-hash-embedding"

    def get_config(self) -> dict[str, Any]:
        return {}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "HashEmbedding":
        return HashEmbedding()

    @staticmethod
    def _embed(text: str) -> list[float]:
        vector = [0.0] * EMBEDDING_DIMENSIONS
        for word in re.findall(r"\w+", text.lower()):
            digest = hashlib.sha256(word.encode()).digest()
            vector[digest[0] % EMBEDDING_DIMENSIONS] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class ScriptedChatModel(BaseChatModel):
    """Fake chat model that replays queued responses and records every prompt it receives.

    ``responses`` holds ``AIMessage``s returned by plain/tool-bound calls. ``structured`` holds
    Pydantic objects (or dicts, validated on use) returned by ``with_structured_output`` calls.
    """

    responses: list[AIMessage] = Field(default_factory=list)
    structured: list[Any] = Field(default_factory=list)
    calls: list[list[BaseMessage]] = Field(default_factory=list)
    tool_bound_calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs):
        self.calls.append(list(messages))
        self.tool_bound_calls += 1
        if not self.responses:
            raise AssertionError("ScriptedChatModel ran out of scripted responses")
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0))])

    def bind_tools(self, tools, **kwargs):
        return self

    def with_structured_output(self, schema, **kwargs):
        def respond(messages: list[BaseMessage]) -> BaseModel:
            self.calls.append(list(messages))
            if not self.structured:
                raise AssertionError("ScriptedChatModel ran out of structured responses")
            item = self.structured.pop(0)
            return item if isinstance(item, BaseModel) else schema.model_validate(item)

        return RunnableLambda(respond)


def tool_call_message(thought: str, name: str, args: dict[str, Any], call_id: str) -> AIMessage:
    """An AIMessage with a thought and one tool call."""
    return AIMessage(content=thought, tool_calls=[{"name": name, "args": args, "id": call_id}])


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings pointing at temporary folders, with a short run timeout."""
    return Settings(
        exec_timeout_seconds=5,
        workspace_root=tmp_path / "workspaces",
        chroma_path=tmp_path / "chroma",
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """An empty workspace folder."""
    path = tmp_path / "workspace"
    path.mkdir()
    return path


@pytest.fixture
def fake_embedding() -> HashEmbedding:
    return HashEmbedding()


@pytest.fixture
def memory(settings: Settings, fake_embedding: HashEmbedding) -> SemanticMemory:
    """A semantic memory on a temporary Chroma folder with the fake embedder."""
    return SemanticMemory.from_settings(settings, embedding_function=fake_embedding)


class RetrieveSpy:
    """Counts calls to ``SemanticMemory.retrieve``."""

    def __init__(self) -> None:
        self.calls = 0


@pytest.fixture
def retrieve_spy(memory: SemanticMemory, monkeypatch: pytest.MonkeyPatch) -> RetrieveSpy:
    spy = RetrieveSpy()
    original = memory.retrieve

    def counting_retrieve(*args, **kwargs):
        spy.calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(memory, "retrieve", counting_retrieve)
    return spy


@pytest.fixture
def make_dependencies(
    settings: Settings, memory: SemanticMemory, retrieve_spy: RetrieveSpy
) -> Callable[..., AgentDependencies]:
    """Factory building dependencies around a ScriptedChatModel and the spied memory."""

    def build(
        responses: list[AIMessage] | None = None, structured: list[Any] | None = None
    ) -> AgentDependencies:
        llm = ScriptedChatModel(responses=responses or [], structured=structured or [])
        return AgentDependencies(
            llm=llm,
            memory=memory,
            buffer=ConversationBuffer(settings.memory_window_turns),
            settings=settings,
        )

    return build


def make_specification(task_count: int = 2) -> TechnicalSpecification:
    """A valid spec: requirements R1..Rn, one criterion each, and tasks T1..Tn where Tk covers Rk
    and depends on Tk-1."""
    numbers = range(1, task_count + 1)
    return TechnicalSpecification(
        name="LA clock",
        description="A command-line tool that prints the current time in Los Angeles.",
        requirements=[Requirement(id=f"R{n}", statement=f"Requirement {n}.") for n in numbers],
        acceptance_criteria=[
            AcceptanceCriterion(id=f"AC{n}", requirement_id=f"R{n}", text=f"Check {n}.")
            for n in numbers
        ],
        out_of_scope=["Other time zones."],
        tasks=[
            PlannedTask(
                id=f"T{n}",
                title=f"Task {n}",
                description=f"Write code for requirement {n}.",
                acceptance_criteria=[f"Requirement {n} works."],
                priority="high",
                covers=[f"R{n}"],
                depends_on=[f"T{n - 1}"] if n > 1 else [],
            )
            for n in numbers
        ],
    )


@pytest.fixture
def specification_draft() -> SpecificationDraft:
    """A PM ``specify`` answer that accepts the requirement with a valid two-task spec."""
    return SpecificationDraft(is_software_requirement=True, specification=make_specification())
