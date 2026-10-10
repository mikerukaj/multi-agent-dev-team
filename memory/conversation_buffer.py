"""Memory layer 1: a sliding window over the most recent ReAct turns."""

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage


class ConversationBuffer:
    """Keeps the last ``max_turns`` turns of the ReAct conversation.

    A turn is one ``AIMessage`` plus the ``ToolMessage``s that answer its tool calls. Turns are
    never split, so the model never sees a tool result without the call that produced it.
    """

    def __init__(self, max_turns: int) -> None:
        if max_turns < 1:
            raise ValueError("max_turns must be at least 1")
        self.max_turns = max_turns

    def window(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        """Return the messages belonging to the last ``max_turns`` turns, in order."""
        turns = self._group_into_turns(messages)
        return [message for turn in turns[-self.max_turns :] for message in turn]

    @staticmethod
    def _group_into_turns(messages: list[BaseMessage]) -> list[list[BaseMessage]]:
        turns: list[list[BaseMessage]] = []
        for message in messages:
            if isinstance(message, ToolMessage) and turns:
                turns[-1].append(message)
            elif isinstance(message, AIMessage) or not turns:
                turns.append([message])
            else:
                turns[-1].append(message)
        return turns
