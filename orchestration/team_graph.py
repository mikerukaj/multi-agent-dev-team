"""The team graph: the PM agent and the Coder agent in one LangGraph graph over ``TeamState``.

specify ─► (consolidate)* ─► dispatch_task ─► coder ─► record_report ─┬─► dispatch_task ...
                                                                      └─► final_run ─► finalize

Public API: ``run_dev_team`` and ``build_team_graph`` (specs/002-pm-agent/contracts/team-api.md).
The handoff protocol is in contracts/handoff-protocol.md.
"""

import argparse
import logging
import sys
import uuid
from pathlib import Path

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agents.coder_agent import RECURSION_LIMIT, build_coder_graph
from agents.dependencies import AgentDependencies
from agents.errors import (
    CoderAgentError,
    InvalidRequirementError,
    LLMServiceError,
    TaskPlanningError,
)
from agents.llm import invoke_model
from agents.pm_agent import PMNodes
from agents.prompts import HANDOFF_TASK_TEMPLATE
from agents.schemas import ExecutionResult, ExecutionStatus
from config import ENTRYPOINT, MAX_CONSOLIDATION_ATTEMPTS, MAX_TASKS, load_settings
from orchestration.protocol import (
    OutcomeStatus,
    TaskHandoff,
    TaskRecord,
    TaskReport,
    TaskStatus,
    TeamOutcome,
    TeamResult,
    build_handoff,
    task_status_for,
)
from orchestration.state import TeamState
from tools.exec_python import run_python_file
from tools.workspace import list_workspace_files, prepare_workspace

logger = logging.getLogger(__name__)

STEPS_PER_TASK = 3
"""Graph steps for one task: dispatch_task, coder, record_report."""

FIXED_STEPS = 3
"""Graph steps every run takes once: specify, final_run, finalize."""

RECURSION_HEADROOM = 5
"""Spare graph steps, matching the Coder agent's recursion limit."""

TEAM_RECURSION_LIMIT = (
    FIXED_STEPS + MAX_CONSOLIDATION_ATTEMPTS + STEPS_PER_TASK * MAX_TASKS + RECURSION_HEADROOM
)
"""Graph steps allowed for one requirement, so the graph cannot loop without bound (research R6).
The Coder subgraph has its own limit."""

FAILED_RUN_STATUSES = frozenset({ExecutionStatus.FAILED, ExecutionStatus.TIMED_OUT})


def run_dev_team(
    requirement: str,
    workspace: Path | None = None,
    *,
    dependencies: AgentDependencies | None = None,
) -> TeamResult:
    """Turn a high-level requirement into a specification, tasks and working code.

    Raises:
        InvalidRequirementError: ``requirement`` is empty or whitespace only.
        InvalidWorkspaceError: ``workspace`` exists and is not empty.
        AgentConfigurationError: the API key is missing or Chroma cannot be opened.
        TaskPlanningError: the task list is still too long after consolidation.
        LLMServiceError: a model call failed or returned an answer that fails validation.
    """
    if not requirement.strip():
        raise InvalidRequirementError("Requirement is empty. Describe the software you want built.")
    run_id = uuid.uuid4().hex
    settings = dependencies.settings if dependencies else load_settings()
    team_workspace = prepare_workspace(workspace, settings.workspace_root, run_id)
    dependencies = dependencies or AgentDependencies.from_settings(settings)

    graph = build_team_graph(dependencies, team_workspace)
    initial_state: TeamState = {"run_id": run_id, "requirement": requirement.strip()}
    final_state = graph.invoke(initial_state, {"recursion_limit": TEAM_RECURSION_LIMIT})
    return final_state["result"]


def build_team_graph(dependencies: AgentDependencies, workspace: Path) -> CompiledStateGraph:
    """Wire the PM nodes, the handoff loop and the Coder subgraph into one compiled graph.

    Both agents share ``dependencies`` (model, memory, settings) and one ``workspace``.
    """
    nodes = _TeamNodes(dependencies, workspace)
    graph = StateGraph(TeamState)
    graph.add_node("specify", nodes.pm.specify)
    graph.add_node("consolidate", nodes.pm.consolidate)
    graph.add_node("dispatch_task", nodes.dispatch_task)
    graph.add_node("coder", nodes.coder)
    graph.add_node("record_report", nodes.record_report)
    graph.add_node("final_run", nodes.final_run)
    graph.add_node("finalize", nodes.finalize)
    graph.add_edge(START, "specify")
    planning_targets = ["consolidate", "dispatch_task", "finalize"]
    graph.add_conditional_edges("specify", route_after_planning, planning_targets)
    graph.add_conditional_edges("consolidate", route_after_planning, planning_targets)
    graph.add_edge("dispatch_task", "coder")
    graph.add_edge("coder", "record_report")
    graph.add_conditional_edges("record_report", route_after_record, ["dispatch_task", "final_run"])
    graph.add_edge("final_run", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


def route_after_planning(state: TeamState) -> str:
    """Finish a declined requirement, consolidate an over-long task list, or start handing off
    tasks (spec FR-004a, FR-012).

    Raises:
        TaskPlanningError: still more than ``MAX_TASKS`` tasks after the allowed attempts.
    """
    if state.get("decline_reason"):
        return "finalize"
    task_count = len(state.get("tasks", []))
    if task_count <= MAX_TASKS:
        return "dispatch_task"
    if state.get("consolidation_attempts", 0) < MAX_CONSOLIDATION_ATTEMPTS:
        return "consolidate"
    raise TaskPlanningError(
        f"The PM agent still planned {task_count} tasks after {MAX_CONSOLIDATION_ATTEMPTS} "
        f"consolidations; at most {MAX_TASKS} are allowed."
    )


def route_after_record(state: TeamState) -> str:
    """Hand off the next task; after a failed task or the last one, go to the final run.

    A failed task stops all later handoffs, so they stay ``not_started`` (spec FR-010a).
    """
    statuses = [record.status for record in state["tasks"]]
    if TaskStatus.FAILED in statuses or TaskStatus.NOT_STARTED not in statuses:
        return "final_run"
    return "dispatch_task"


class _TeamNodes:
    """Team graph nodes for one requirement. Holds the PM nodes and the compiled Coder graph."""

    def __init__(self, dependencies: AgentDependencies, workspace: Path) -> None:
        self.dependencies = dependencies
        self.workspace = workspace
        self.pm = PMNodes(dependencies)
        self.coder_graph = build_coder_graph(dependencies, workspace)

    def dispatch_task(self, state: TeamState) -> TeamState:
        """Write the next task's handoff to ``current_handoff``: the "task ready" signal."""
        tasks = list(state["tasks"])
        index = next(i for i, r in enumerate(tasks) if r.status == TaskStatus.NOT_STARTED)
        workspace_files = [file.path for file in list_workspace_files(self.workspace)]
        handoff = build_handoff(
            state["specification"], tasks[index].task, state["run_id"], workspace_files
        )
        tasks[index] = TaskRecord(
            task=tasks[index].task, status=TaskStatus.IN_PROGRESS, handoff=handoff
        )
        logger.info("Task %s handed off", handoff.task_id)
        return {"tasks": tasks, "current_handoff": handoff}

    def coder(self, state: TeamState) -> TeamState:
        """Run the Coder subgraph on the current handoff and return its report."""
        handoff = state["current_handoff"]
        coder_state = {
            "run_id": f"{state['run_id']}:{handoff.task_id}",
            "task": render_handoff(handoff),
            "messages": [],
        }
        stage = f"Task {handoff.task_id}"
        try:
            final_state = invoke_model(
                self.coder_graph, coder_state, stage, {"recursion_limit": RECURSION_LIMIT}
            )
        except CoderAgentError as error:
            raise type(error)(f"{stage} failed: {error}") from error
        result = final_state["result"]
        report = TaskReport(
            task_id=handoff.task_id, status=task_status_for(result), coder_result=result
        )
        return {"last_report": report}

    def record_report(self, state: TeamState) -> TeamState:
        """Store the report on its task, update the status and code, and clear the handoff."""
        report = state["last_report"]
        expected = state["current_handoff"].task_id
        if report.task_id != expected:
            raise LLMServiceError(
                f"Task report for {report.task_id} does not match handoff {expected}"
            )
        tasks = [
            record.model_copy(update={"status": report.status, "report": report})
            if record.task.id == report.task_id
            else record
            for record in state["tasks"]
        ]
        logger.info("Task %s %s", report.task_id, report.status)
        return {
            "tasks": tasks,
            "code": list_workspace_files(self.workspace),
            "current_handoff": None,
            "last_report": None,
        }

    def final_run(self, state: TeamState) -> TeamState:
        """Run the finished program once, with no model call (spec FR-016)."""
        if (self.workspace / ENTRYPOINT).is_file():
            settings = self.dependencies.settings
            execution = run_python_file(
                self.workspace,
                ENTRYPOINT,
                settings.exec_timeout_seconds,
                settings.max_output_chars,
            )
        else:
            execution = ExecutionResult.not_run()
        logger.info("Final run %s", execution.status)
        return {"final_execution": execution, "code": list_workspace_files(self.workspace)}

    def finalize(self, state: TeamState) -> TeamState:
        """Build and validate the ``TeamResult`` (spec FR-011)."""
        execution = state.get("final_execution") or ExecutionResult.not_run()
        result = TeamResult(
            specification=state.get("specification"),
            tasks=state.get("tasks", []),
            code=state.get("code", []),
            execution_result=execution,
            outcome=_outcome(state, execution),
        )
        return {"result": result}


def _outcome(state: TeamState, execution: ExecutionResult) -> TeamOutcome:
    """Completed, failed (naming what failed) or declined (clarification Q4)."""
    if state.get("decline_reason"):
        return TeamOutcome(status=OutcomeStatus.DECLINED, reason=state["decline_reason"])
    tasks = state.get("tasks", [])
    failed_task = next((r.task.id for r in tasks if r.status == TaskStatus.FAILED), None)
    if failed_task:
        return TeamOutcome(status=OutcomeStatus.FAILED, reason=f"Task {failed_task} failed.")
    if execution.status in FAILED_RUN_STATUSES:
        return TeamOutcome(status=OutcomeStatus.FAILED, reason=f"The final run {execution.status}.")
    return TeamOutcome(
        status=OutcomeStatus.COMPLETED,
        reason=f"All {len(tasks)} tasks completed and the final run {execution.status}.",
    )


def render_handoff(handoff: TaskHandoff) -> str:
    """Render a handoff as the Coder agent's task text (research R4)."""
    context = handoff.context
    return HANDOFF_TASK_TEMPLATE.format(
        task_id=handoff.task_id,
        priority=handoff.priority,
        title=handoff.title,
        description=handoff.description,
        task_criteria=_bullets(handoff.acceptance_criteria),
        spec_name=context.name,
        spec_description=context.description,
        requirements=_bullets(f"{r.id}: {r.statement}" for r in context.requirements),
        spec_criteria=_bullets(f"{c.id}: {c.text}" for c in context.acceptance_criteria),
        out_of_scope=_bullets(context.out_of_scope),
        workspace_files=_bullets(handoff.workspace_files),
    )


def _bullets(items) -> str:
    lines = [f"- {item}" for item in items]
    return "\n".join(lines) if lines else "(none)"


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point: ``python -m orchestration.team_graph "<requirement>"``."""
    parser = argparse.ArgumentParser(description="Run the PM and Coder agents on one requirement.")
    parser.add_argument("requirement", help="High-level software requirement.")
    parser.add_argument("--workspace", type=Path, help="Empty or missing folder to work in.")
    args = parser.parse_args(argv)

    settings = load_settings()
    logging.basicConfig(level=settings.log_level, stream=sys.stderr)
    try:
        result = run_dev_team(args.requirement, workspace=args.workspace)
    except CoderAgentError as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
