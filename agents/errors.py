"""Errors raised by the Coder agent's public API.

Failures of the *generated* code are never raised; they are reported in ``execution_result``.
"""


class CoderAgentError(Exception):
    """Base class for every error the Coder agent raises."""


class InvalidTaskError(CoderAgentError):
    """The task is empty or whitespace only. Raised before any work is done."""


class InvalidWorkspaceError(CoderAgentError):
    """The supplied workspace exists and is not empty. Raised before any work is done."""


class AgentConfigurationError(CoderAgentError):
    """A required setting is missing or a dependency (such as Chroma) cannot be opened."""


class LLMServiceError(CoderAgentError):
    """The model call failed after retries, or its structured answer could not be parsed."""
