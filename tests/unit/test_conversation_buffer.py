"""Sliding-window memory (research R4)."""

from langchain_core.messages import AIMessage, ToolMessage

from memory.conversation_buffer import ConversationBuffer


def _turn(number: int, tool_calls: int = 1) -> list:
    calls = [{"name": "read_file", "args": {}, "id": f"{number}-{i}"} for i in range(tool_calls)]
    messages = [AIMessage(content=f"thought {number}", tool_calls=calls)]
    messages += [ToolMessage(content=f"obs {number}", tool_call_id=c["id"]) for c in calls]
    return messages


def test_keeps_only_last_n_turns():
    messages = _turn(1) + _turn(2) + _turn(3)
    window = ConversationBuffer(max_turns=2).window(messages)
    assert window == _turn(2) + _turn(3)


def test_never_returns_tool_message_without_its_ai_message():
    messages = _turn(1) + _turn(2, tool_calls=2) + _turn(3)
    window = ConversationBuffer(max_turns=2).window(messages)
    assert isinstance(window[0], AIMessage)


def test_ai_message_with_two_tool_calls_is_one_turn():
    messages = _turn(1, tool_calls=2)
    assert ConversationBuffer(max_turns=1).window(messages) == messages


def test_returns_everything_when_fewer_turns_than_window():
    messages = _turn(1)
    assert ConversationBuffer(max_turns=6).window(messages) == messages
