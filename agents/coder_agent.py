"""The Coder agent: plan -> ReAct loop (reason <-> act) -> finalize, built with LangGraph.

Public API: ``run_coder_agent`` and ``build_coder_graph``
(specs/001-coder-agent/contracts/coder-agent-api.md).
"""

import argparse
import logging
import sys
import uuid
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agents.context import build_llm_messages
from agents.dependencies import AgentDependencies
from agents.errors import CoderAgentError, InvalidTaskError, LLMServiceError
from agents.prompts import EXPLANATION_PROMPT, PLAN_PROMPT, REASON_STATUS_TEMPLATE
from agents.schemas import (
    CoderResult,
    ExecutionPlan,
    ExecutionResult,
    ExplanationDraft,
    PlanDecision,
    ReActStep,
    StopReason,
)
from agents.state import CoderState
from config import ENTRYPOINT, MAX_ITERATIONS, MAX_REVISIONS, load_settings
from memory.semantic_memory import MemoryRecord
from tools.exec_python import make_exec_python_tool, run_python_file
from tools.file_tools import make_file_tools, truncate_for_observation
from tools.workspace import list_workspace_files, prepare_workspace

logger = logging.getLogger(__name__)

RECURSION_LIMIT = 2 * MAX_ITERATIONS + 5
"""Graph steps allowed: plan + up to 10 reason/act pairs + finalize, with headroom."""

FAILED_STATUSES = frozenset({"failed", "timed_out"})


def run_coder_agent(
    task: str, workspace: Path | None = None, *, dependencies: AgentDependencies | None = None
) -> CoderResult:
    """Solve a natural language coding task and return the validated structured result.

    Raises:
        InvalidTaskError: the task is empty.
        InvalidWorkspaceError: ``workspace`` exists and is not empty.
        AgentConfigurationError: the API key is missing or Chroma cannot be opened.
        LLMServiceError: a model call failed after retries or returned an unusable answer.
    """
    if not task.strip():
        raise InvalidTaskError("Task is empty. Describe the program you want written.")
    run_id = uuid.uuid4().hex
    settings = dependencies.settings if dependencies else load_settings()
    task_workspace = prepare_workspace(workspace, settings.workspace_root, run_id)
    dependencies = dependencies or AgentDependencies.from_settings(settings)

    graph = build_coder_graph(dependencies, task_workspace)
    initial_state: CoderState = {"run_id": run_id, "task": task.strip(), "messages": []}
    final_state = graph.invoke(initial_state, {"recursion_limit": RECURSION_LIMIT})
    return final_state["result"]


def build_coder_graph(dependencies: AgentDependencies, workspace: Path) -> CompiledStateGraph:
    """Wire the plan -> reason <-> act -> finalize graph for one workspace."""
    nodes = _CoderNodes(dependencies, workspace)
    graph = StateGraph(_GraphState)
    graph.add_node("plan", nodes.plan)
    graph.add_node("reason", nodes.reason)
    graph.add_node("act", nodes.act)
    graph.add_node("finalize", nodes.finalize)
    graph.add_edge(START, "plan")
    graph.add_conditional_edges("plan", route_after_plan, ["reason", "finalize"])
    graph.add_conditional_edges("reason", route_after_reason, ["act", "finalize"])
    graph.add_conditional_edges("act", route_after_act, ["reason", "finalize"])
    graph.add_edge("finalize", END)
    return graph.compile()


class _GraphState(CoderState, total=False):
    """Graph state plus the final result written by ``finalize``."""

    result: CoderResult


def route_after_plan(state: CoderState) -> str:
    """Rejected tasks go straight to finalize; coding tasks start the ReAct loop."""
    return "reason" if state.get("is_coding_task") else "finalize"


def route_after_reason(state: CoderState) -> str:
    """Run tools if the model asked for any; otherwise the model is done."""
    return "act" if _last_ai_message(state).tool_calls else "finalize"


def route_after_act(state: CoderState) -> str:
    """Stop when a revision or iteration limit is reached; otherwise reason again."""
    return "finalize" if limit_stop_reason(state) else "reason"


def limit_stop_reason(state: CoderState) -> StopReason | None:
    """Return why a limit ends the loop now, or None to keep going (research R3).

    The revision limit is checked before the iteration limit.
    """
    if state.get("revision_attempts", 0) >= MAX_REVISIONS:
        last_run = state.get("last_execution")
        if last_run is not None and last_run.success:
            return StopReason.COMPLETED
        return StopReason.REVISION_LIMIT
    if state.get("iteration", 0) >= MAX_ITERATIONS:
        return StopReason.ITERATION_LIMIT
    return None


class _CoderNodes:
    """Graph nodes for one task. Holds the dependencies and the workspace's tools."""

    def __init__(self, dependencies: AgentDependencies, workspace: Path) -> None:
        self.dependencies = dependencies
        self.workspace = workspace
        settings = dependencies.settings
        tools = [*make_file_tools(workspace, settings), make_exec_python_tool(workspace, settings)]
        self.tools = {tool.name: tool for tool in tools}
        self.tool_model = dependencies.llm.bind_tools(tools)

    def plan(self, state: CoderState) -> dict[str, Any]:
        """Decide whether this is a coding task and make the ordered plan (spec FR-002)."""
        messages = build_llm_messages(state, PLAN_PROMPT, self.dependencies)
        decision = _invoke_model(
            self.dependencies.llm.with_structured_output(PlanDecision, method="json_schema"),
            messages,
        )
        self._remember(
            [
                MemoryRecord(kind="task", text=state["task"], run_id=state["run_id"]),
                MemoryRecord(kind="plan", text="\n".join(decision.steps), run_id=state["run_id"]),
            ],
        )
        return {
            "plan_steps": decision.steps,
            "is_coding_task": decision.is_coding_task,
            "rejection_reason": decision.rejection_reason,
            "trace": [],
            "iteration": 0,
            "first_failure_seen": False,
            "revision_attempts": 0,
            "last_execution": None,
            "files_changed_since_run": False,
        }

    def reason(self, state: CoderState) -> dict[str, Any]:
        """One Thought (+ Action request) from the tool-bound model."""
        iteration = state["iteration"] + 1
        status = REASON_STATUS_TEMPLATE.format(
            iteration=iteration,
            max_iterations=MAX_ITERATIONS,
            revisions=state["revision_attempts"],
            max_revisions=MAX_REVISIONS,
        )
        response = _invoke_model(
            self.tool_model, build_llm_messages(state, status, self.dependencies)
        )
        thought = response.text.strip()
        self._remember(
            [
                MemoryRecord(
                    kind="thought", text=thought, run_id=state["run_id"], iteration=iteration
                )
            ],
        )
        return {"iteration": iteration, "messages": [*state["messages"], response]}

    def act(self, state: CoderState) -> dict[str, Any]:
        """Run every tool the model asked for and record each Observation."""
        ai_message = _last_ai_message(state)
        updates: dict[str, Any] = {
            "messages": list(state["messages"]),
            "trace": list(state["trace"]),
            "first_failure_seen": state["first_failure_seen"],
            "revision_attempts": state["revision_attempts"],
            "last_execution": state["last_execution"],
            "files_changed_since_run": state["files_changed_since_run"],
        }
        for tool_call in ai_message.tool_calls:
            tool_message = self._run_tool(tool_call)
            updates["messages"].append(tool_message)
            updates["trace"].append(self._trace_step(state, ai_message, tool_call, tool_message))
            _apply_tool_side_effects(updates, tool_call["name"], tool_message)
            self._remember(
                [
                    MemoryRecord(
                        kind="observation",
                        text=f"{tool_call['name']}: {tool_message.content}",
                        run_id=state["run_id"],
                        iteration=state["iteration"],
                    )
                ],
            )
        return updates

    def finalize(self, state: CoderState) -> dict[str, Any]:
        """Build the result from the real workspace and the last real run (research R9)."""
        if not state.get("is_coding_task"):
            result = self._rejected_result(state)
        else:
            result = self._completed_result(state)
        self._remember(
            [
                MemoryRecord(
                    kind="result",
                    text=f"Task: {state['task']}\nOutcome: {result.plan.stop_reason}, "
                    f"run {result.execution_result.status}.\n{result.explanation}",
                    run_id=state["run_id"],
                )
            ],
        )
        return {"result": result}

    def _completed_result(self, state: CoderState) -> CoderResult:
        execution = self._final_execution(state)
        stop_reason = limit_stop_reason(state) or StopReason.COMPLETED
        trace = list(state["trace"])
        last_message = _last_ai_message(state)
        if stop_reason == StopReason.COMPLETED and not last_message.tool_calls:
            trace.append(ReActStep(iteration=state["iteration"], thought=last_message.text.strip()))
        files = list_workspace_files(self.workspace)
        explanation = self._explain(state, files, execution)
        return CoderResult(
            code=files,
            explanation=explanation,
            plan=ExecutionPlan(
                steps=state["plan_steps"],
                trace=trace,
                iterations=state["iteration"],
                revision_attempts=state["revision_attempts"],
                stop_reason=stop_reason,
            ),
            execution_result=execution,
        )

    def _rejected_result(self, state: CoderState) -> CoderResult:
        return CoderResult(
            code=[],
            explanation=f"Task rejected: {state['rejection_reason']}",
            plan=ExecutionPlan(
                steps=state["plan_steps"],
                iterations=0,
                revision_attempts=0,
                stop_reason=StopReason.REJECTED,
            ),
            execution_result=ExecutionResult.not_run(),
        )

    def _final_execution(self, state: CoderState) -> ExecutionResult:
        """The last real run, re-running the entry point if code changed since (spec FR-010)."""
        last_run = state.get("last_execution")
        is_stale = last_run is None or state.get("files_changed_since_run", False)
        if is_stale and (self.workspace / ENTRYPOINT).is_file():
            settings = self.dependencies.settings
            return run_python_file(
                self.workspace,
                ENTRYPOINT,
                settings.exec_timeout_seconds,
                settings.max_output_chars,
            )
        return last_run or ExecutionResult.not_run()

    def _explain(self, state: CoderState, files: list, execution: ExecutionResult) -> str:
        settings = self.dependencies.settings
        file_text = "\n\n".join(
            f"--- {file.path} ---\n"
            f"{truncate_for_observation(file.content, settings.max_observation_chars)}"
            for file in files
        )
        instruction = EXPLANATION_PROMPT.format(
            files=file_text or "(no files)",
            execution_result=execution.model_dump_json(indent=2),
        )
        messages = build_llm_messages(
            state, instruction, self.dependencies, include_conversation=False
        )
        draft = _invoke_model(
            self.dependencies.llm.with_structured_output(ExplanationDraft, method="json_schema"),
            messages,
        )
        return draft.explanation

    def _run_tool(self, tool_call: dict[str, Any]) -> ToolMessage:
        tool = self.tools.get(tool_call["name"])
        if tool is None:
            return ToolMessage(
                content=f"ERROR: unknown tool {tool_call['name']}", tool_call_id=tool_call["id"]
            )
        return tool.invoke({**tool_call, "type": "tool_call"})

    def _trace_step(
        self,
        state: CoderState,
        ai_message: AIMessage,
        tool_call: dict[str, Any],
        tool_message: ToolMessage,
    ) -> ReActStep:
        action_input = dict(tool_call["args"])
        if tool_call["name"] == "write_file" and "content" in action_input:
            action_input["content"] = f"<{len(str(action_input['content']))} chars>"
        observation = truncate_for_observation(
            str(tool_message.content), self.dependencies.settings.max_observation_chars
        )
        return ReActStep(
            iteration=state["iteration"],
            thought=ai_message.text.strip(),
            action=tool_call["name"],
            action_input=action_input,
            observation=observation,
        )

    def _remember(self, records: list[MemoryRecord]) -> None:
        """Store records in long-term memory."""
        self.dependencies.memory.add(records)


def _apply_tool_side_effects(
    updates: dict[str, Any], tool_name: str, tool_message: ToolMessage
) -> None:
    """Update run-tracking state after a tool call (contracts/tools.md, data-model.md)."""
    if tool_name == "write_file" and str(tool_message.content).startswith("Wrote"):
        updates["files_changed_since_run"] = True
        return
    if tool_name != "exec_python" or tool_message.artifact is None:
        return
    result: ExecutionResult = tool_message.artifact
    updates["last_execution"] = result
    updates["files_changed_since_run"] = False
    if updates["first_failure_seen"]:
        updates["revision_attempts"] += 1
    if result.status in FAILED_STATUSES:
        updates["first_failure_seen"] = True


def _last_ai_message(state: CoderState) -> AIMessage:
    for message in reversed(state.get("messages", [])):
        if isinstance(message, AIMessage):
            return message
    return AIMessage(content="")


def _invoke_model(model: Any, messages: list[BaseMessage]) -> Any:
    """Call the model, turning any failure into ``LLMServiceError``."""
    try:
        return model.invoke(messages)
    except CoderAgentError:
        raise
    except Exception as error:
        raise LLMServiceError(f"Model call failed: {error}") from error


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point: ``python -m agents.coder_agent "<task>" [--workspace PATH]``."""
    parser = argparse.ArgumentParser(description="Run the Coder agent on one coding task.")
    parser.add_argument("task", help="Natural language coding task.")
    parser.add_argument("--workspace", type=Path, help="Empty or missing folder to work in.")
    args = parser.parse_args(argv)

    settings = load_settings()
    logging.basicConfig(level=settings.log_level, stream=sys.stderr)
    try:
        result = run_coder_agent(args.task, workspace=args.workspace)
    except CoderAgentError as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
