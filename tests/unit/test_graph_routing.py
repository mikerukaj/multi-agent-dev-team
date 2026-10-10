"""Happy path through the LangGraph agent with a scripted model (spec US1)."""

from langchain_core.messages import AIMessage

from agents.coder_agent import run_coder_agent
from agents.schemas import (
    CoderResult,
    ExplanationDraft,
    GeneratedFile,
    PlanDecision,
    StopReason,
)
from tests.conftest import tool_call_message

TASK = "Write a python program that prints hi"
SOURCE = 'print("hi")'


def _happy_path_script():
    responses = [
        tool_call_message(
            "I'll write main.py.", "write_file", {"path": "main.py", "content": SOURCE}, "c1"
        ),
        tool_call_message("Now run it.", "exec_python", {"path": "main.py"}, "c2"),
        AIMessage(content="It printed hi. Done."),
    ]
    structured = [
        PlanDecision(steps=["Write main.py", "Run it", "Check output"], is_coding_task=True),
        ExplanationDraft(explanation="main.py prints hi. Run it with `python main.py`."),
    ]
    return responses, structured


def test_happy_path_returns_validated_result(make_dependencies, workspace, retrieve_spy, memory):
    responses, structured = _happy_path_script()
    dependencies = make_dependencies(responses, structured)

    result = run_coder_agent(TASK, workspace=workspace, dependencies=dependencies)

    assert isinstance(result, CoderResult)
    assert result.plan.stop_reason == StopReason.COMPLETED
    assert result.plan.iterations == 3
    assert result.plan.revision_attempts == 0
    assert result.code == [GeneratedFile(path="main.py", content=SOURCE)]
    assert (workspace / "main.py").read_text() == SOURCE
    assert result.execution_result.success
    assert result.execution_result.stdout == "hi\n"
    assert result.explanation.startswith("main.py prints hi")

    trace = result.plan.trace
    assert [step.action for step in trace] == ["write_file", "exec_python", None]
    assert trace[0].thought == "I'll write main.py."
    assert trace[0].action_input == {"path": "main.py", "content": f"<{len(SOURCE)} chars>"}
    assert trace[0].observation.startswith("Wrote")
    assert trace[1].observation.startswith("status=succeeded")
    assert trace[2].thought == "It printed hi. Done." and trace[2].observation is None

    assert retrieve_spy.calls == 5  # plan, three reason rounds, explanation
    stored_kinds = {record.kind for record in memory.recent(100)}
    assert stored_kinds == {"task", "plan", "thought", "observation", "result"}
