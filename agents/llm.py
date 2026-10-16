"""The one place model failures become ``LLMServiceError`` (constitution Principle I, research R10).

Every model call made by the Coder agent and the PM agent, and the team graph's call into the
Coder subgraph, goes through ``invoke_model``.
"""

from typing import Any

from langchain_core.runnables import Runnable, RunnableConfig

from agents.errors import CoderAgentError, LLMServiceError

DEFAULT_STAGE = "Model call"
"""Stage name used when the caller gives none; keeps the Coder agent's original error text."""


def invoke_model(
    runnable: Runnable,
    payload: Any,
    stage: str = DEFAULT_STAGE,
    config: RunnableConfig | None = None,
) -> Any:
    """Invoke ``runnable`` and return its output.

    Args:
        runnable: A chat model, a structured-output chain, or a compiled graph.
        payload: The messages or state passed to ``runnable.invoke``.
        stage: Names the failing step in the error, e.g. ``"PM specify"``.
        config: Optional LangChain run config (for example a graph recursion limit).

    Raises:
        CoderAgentError: unchanged, when ``runnable`` raised one itself.
        LLMServiceError: ``"<stage> failed: <error>"`` for any other failure.
    """
    try:
        return runnable.invoke(payload, config)
    except CoderAgentError:
        raise
    except Exception as error:
        raise LLMServiceError(f"{stage} failed: {error}") from error
