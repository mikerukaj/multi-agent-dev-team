"""Single source of configuration for the Coder agent (constitution Principle V).

Fixed values are module constants. Values that may differ between environments are fields on
``Settings`` and can be overridden with environment variables (or a ``.env`` file).
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

CODER_MODEL = "claude-sonnet-5-5"
"""The only LLM the project uses (constitution Principle IV)."""

MAX_ITERATIONS = 10
"""Maximum ReAct reason/act rounds per task."""

MAX_REVISIONS = 3
"""Maximum code runs after the first failed run."""

ENTRYPOINT = "main.py"
"""File the agent writes as the program's entry point and runs by default."""

MEMORY_COLLECTION = "coder_agent_memory"
"""Chroma collection holding the agent's long-term memory."""


@dataclass(frozen=True)
class Settings:
    """Environment-dependent settings. Build with ``load_settings()``."""

    exec_timeout_seconds: float = 30.0
    """Seconds before a run of generated code is killed."""

    max_output_chars: int = 10_000
    """Characters kept from each of stdout and stderr of a run."""

    max_observation_chars: int = 4_000
    """Characters of a tool result shown to the model per observation."""

    memory_window_turns: int = 6
    """Recent ReAct turns kept in the sliding-window buffer."""

    memory_top_k: int = 4
    """Maximum past-context records retrieved before each LLM call."""

    memory_max_distance: float = 1.2
    """Maximum embedding distance for a retrieved record to count as relevant."""

    workspace_root: Path = Path("workspace")
    """Folder under which each task gets its own new workspace."""

    chroma_path: Path = Path(".chroma")
    """Folder for the embedded Chroma store."""

    chroma_host: str | None = None
    """Chroma server host; None means use the embedded store at ``chroma_path``."""

    chroma_port: int = 8000
    """Chroma server port, used only when ``chroma_host`` is set."""

    llm_max_tokens: int = 8192
    """Maximum output tokens per model call."""

    llm_max_retries: int = 2
    """Retries the Anthropic client makes before a call fails."""

    log_level: str = "INFO"
    """Python logging level name."""


def _env(name: str) -> str | None:
    """Return the env variable's value, treating an empty string as unset."""
    value = os.environ.get(name, "").strip()
    return value or None


def load_settings() -> Settings:
    """Load ``.env`` (if present) and build ``Settings`` from environment overrides."""
    load_dotenv()
    defaults = Settings()

    def read(name: str, default, cast):
        value = _env(name)
        return default if value is None else cast(value)

    return Settings(
        exec_timeout_seconds=read("EXEC_TIMEOUT_SECONDS", defaults.exec_timeout_seconds, float),
        max_output_chars=read("MAX_OUTPUT_CHARS", defaults.max_output_chars, int),
        max_observation_chars=read("MAX_OBSERVATION_CHARS", defaults.max_observation_chars, int),
        memory_window_turns=read("MEMORY_WINDOW_TURNS", defaults.memory_window_turns, int),
        memory_top_k=read("MEMORY_TOP_K", defaults.memory_top_k, int),
        memory_max_distance=read("MEMORY_MAX_DISTANCE", defaults.memory_max_distance, float),
        workspace_root=read("WORKSPACE_ROOT", defaults.workspace_root, Path),
        chroma_path=read("CHROMA_PATH", defaults.chroma_path, Path),
        chroma_host=read("CHROMA_HOST", defaults.chroma_host, str),
        chroma_port=read("CHROMA_PORT", defaults.chroma_port, int),
        llm_max_tokens=read("LLM_MAX_TOKENS", defaults.llm_max_tokens, int),
        llm_max_retries=read("LLM_MAX_RETRIES", defaults.llm_max_retries, int),
        log_level=read("LOG_LEVEL", defaults.log_level, str).upper(),
    )
