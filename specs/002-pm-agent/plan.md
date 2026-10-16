# Implementation Plan: PM Agent and PM-to-Coder Handoff

**Branch**: `002-pm-agent` | **Date**: 2026-10-15 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-pm-agent/spec.md`, plus the `/speckit-plan`
input (the PM spec fields, the handoff protocol fields including priority, consolidation above 8
tasks, a single graph, JSON-serializable messages, and the README diagram).

## Summary

Add a PM agent in front of the existing Coder agent. Both agents run in **one LangGraph graph**
(the "team graph") over one shared `TeamState`:

1. **PM nodes**:
   - `specify` makes one structured model call. It turns the free-text requirement into a
     `TechnicalSpecification` (name, description, requirements, acceptance criteria, assumptions,
     out-of-scope items, and tasks) and writes it, with one `TaskRecord` per task, into shared
     state.
   - If there are more than 8 tasks, `consolidate` merges them, at most 2 times
     ([research R6](research.md#r6-loop-prevention-consolidating-an-over-long-task-list)).
2. **Handoff**: `dispatch_task` writes the next task's `TaskHandoff` to
   `TeamState.current_handoff`, which is the "task ready" signal. It contains the task ID,
   description, acceptance criteria, priority, dependencies, the covered parts of the spec, and the
   files already in the workspace.
3. **Coder node**: runs the existing Coder graph unchanged, as a subgraph, on the rendered handoff.
   It returns a `TaskReport`.
4. **Progress**: `record_report` writes each task's status, report and the current workspace code
   back to shared state. A failed task stops later handoffs.
5. **End**: `final_run` runs `main.py` once with no model call. `finalize` builds the validated
   `TeamResult` and its outcome (`completed`, `failed` or `declined`).

The Coder-only API, CLI and smoke test are unchanged.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: No new packages. `langgraph==1.2.12`, `langchain-anthropic==1.7.4`,
`langchain-core==1.6.5`, `pydantic==2.13.5` and `chromadb`, as already pinned in
`requirements.txt`.

**LLM**: Claude Sonnet 5.5, `claude-sonnet-5-5`, for both agents (constitution Principle IV). PM
structured calls use `method="json_schema"`, like the Coder agent's.

**Storage**: The same Chroma collection as the Coder agent ([R9](research.md#r9-memory-for-the-pm-agent)).
There's one shared workspace folder per requirement under `workspace/<run_id>/`.

**Testing**: `pytest`. Unit tests use the existing `ScriptedChatModel` and the temporary Chroma
fixtures. There's one new `smoke` test, and the existing smoke test is unchanged. Linting with
`ruff`.

**Target Platform**: Linux (local and the repo's Docker image)

**Project Type**: Python library with CLI entry points (`python -m orchestration.team_graph`, plus
the existing `python -m agents.coder_agent`).

**Performance Goals**: The smoke requirement completes in under 10 minutes (SC-003). A typical run
makes 1 PM call plus 3–5 Coder calls per task, and the final run makes no model call. There's no
run-wide call cap (clarification 2026-10-15). The worst case is bounded at 99 calls: 1 + 2
consolidations + 8 tasks × 12 Coder calls.

**Constraints**:

- At most 8 tasks and at most 2 consolidation attempts.
- Tasks run one at a time, in list order, with no parallelism.
- The team graph's recursion limit is derived from these limits.
- The Coder agent's per-task limits still apply: 10 rounds, 3 revisions, and a 30 s run timeout.
- Each handoff carries only the covered requirements, to limit tokens (clarification Q5).

**Scale/Scope**: One requirement per call, one developer at a time.

No open NEEDS CLARIFICATION items; all were resolved in [research.md](research.md).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | How the design complies | Pre-research | Post-design |
|-----------|------------------------|:---:|:---:|
| I. Clean Code | New code is in small modules: `pm_agent.py` (PM nodes), `protocol.py` (models and `build_handoff`), `state.py`, and `team_graph.py` (wiring, Coder node, CLI). Limits are named constants (`MAX_TASKS`, `MAX_CONSOLIDATION_ATTEMPTS`) in `config.py`. Prompts are in `agents/prompts.py`. Memory retrieval is pulled into one shared helper instead of being copied ([R9](research.md#r9-memory-for-the-pm-agent)), and so is the model-call error wrapping, `agents/llm.py:invoke_model` ([R10](research.md#r10-progress-output-and-errors)), which replaces the Coder agent's private `_invoke_model` without changing its API. Errors are typed. Ruff gate. | ✅ | ✅ |
| II. Structured Agent Outputs | The PM agent's output (`SpecificationDraft` → `TechnicalSpecification`), the handoff, the report and `TeamResult` are all Pydantic models with `extra="forbid"`. Cross-field validators raise on bad dependencies, uncovered requirements and inconsistent outcomes, and everything is validated before it enters `TeamState` ([data-model.md](data-model.md)). The protocol is versioned (`protocol_version`). | ✅ | ✅ |
| III. Smoke Test Gate | A new `tests/integration/test_smoke_team.py` runs the compiled team graph on the spec FR-014 requirement and skips with a reason when there's no key ([contract](contracts/team-api.md#smoke-test-contract-constitution-principle-iii-spec-fr-014)). The Coder-only smoke test is unchanged. | ✅ | ✅ |
| IV. Mandated Stack | All orchestration is one LangGraph graph; the Coder agent is a subgraph in it, with no separate process or ad-hoc loop ([R1](research.md#r1-one-graph-for-both-agents)). One model, `claude-sonnet-5-5`, comes from `config.CODER_MODEL`. All memory is in Chroma. | ✅ | ✅ |
| V. Simplicity & Config | No new dependencies. One PM call in the normal case, and the consolidation call only when needed. No re-planning or retry machinery beyond the required consolidation. The new limits are in `config.py`. | ✅ | ✅ |

**Gate result**: PASS. No violations, so Complexity Tracking is empty.

Note on Principle II: `TeamResult` is a new output schema, and `CoderResult` is unchanged. The
`MemoryRecord.kind` docstring gains two values, which isn't an output schema change.

## System Diagram (to be added to README.md)

```text
           requirement (free text)
                       │
┌──────────────────────┼─────────────────────────────────────────────┐
│ Team graph: one LangGraph StateGraph, one process                  │
│                      ▼                                             │
│  PM agent     ┌─────────────┐  declined                            │
│               │   specify   │───────────────────────────────┐      │
│               └──────┬──────┘                               │      │
│    > 8 tasks         │                                      │      │
│ ┌─────────────┐      │                                      │      │
│ │ consolidate │◄─────┤ (at most 2 times,                    │      │
│ │             │─────►│  then TaskPlanningError)             │      │
│ └─────────────┘      │ ≤ 8 tasks                            │      │
│                      ▼                                      │      │
│  Handoff     ┌───────────────┐                              │      │
│       ┌─────►│ dispatch_task │                              │      │
│       │      └───────┬───────┘                              │      │
│       │              │ current_handoff (TaskHandoff)        │      │
│       │              ▼                                      │      │
│  Coder│      ┌───────────────────────────┐                  │      │
│  agent│      │ coder: the Coder subgraph │                  │      │
│       │      │ plan → reason ⇄ act →     │                  │      │
│       │      │ finalize                  │                  │      │
│       │      └───────┬───────────────────┘                  │      │
│       │              │ last_report (TaskReport)             │      │
│       │              ▼                                      │      │
│  next │      ┌───────────────┐                              │      │
│  task └──────│ record_report │                              │      │
│              └───────┬───────┘                              │      │
│                      │ a task failed, or none left          │      │
│                      ▼                                      │      │
│              ┌───────────────┐    ┌──────────┐              │      │
│              │   final_run   │───►│ finalize │◄─────────────┘      │
│              └───────────────┘    └────┬─────┘                     │
│                                        ▼                           │
│                                    TeamResult                      │
│                                                                    │
│  Shared TeamState: requirement · specification · tasks (each with  │
│  status, handoff, report) · current_handoff · last_report · code · │
│  final_execution · result                                          │
└────────────────────────────────────────────────────────────────────┘
  Both agents ──► Chroma memory (retrieve before every model call)
  coder + final_run ──► shared workspace/<run_id>/
```

## Project Structure

### Documentation (this feature)

```text
specs/002-pm-agent/
├── plan.md              # This file
├── research.md          # Phase 0: decisions R1–R11
├── data-model.md        # Phase 1: spec, handoff, report, TeamState, TeamResult
├── quickstart.md        # Phase 1: validation guide
├── contracts/
│   ├── team-api.md          # run_dev_team, build_team_graph, PMNodes, CLI, smoke contract
│   └── handoff-protocol.md  # TaskHandoff / TaskReport lifecycle, JSON examples, status rule
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks — not created here)
```

### Source Code (repository root)

The new code goes in the existing `orchestration/` placeholder and the empty
`agents/pm_agent.py`. `agents/qa_agent.py` stays empty.

```text
config.py                    # + MAX_TASKS = 8, MAX_CONSOLIDATION_ATTEMPTS = 2

agents/
├── llm.py                   # NEW: invoke_model() — the one place model errors become LLMServiceError
├── pm_agent.py              # NEW: PMNodes.specify / .consolidate; memory records for the PM
├── prompts.py               # + PM_SYSTEM_PROMPT, SPECIFY_PROMPT, CONSOLIDATE_PROMPT, HANDOFF_TASK_TEMPLATE
├── context.py               # retrieve_past_context() extracted; + build_pm_messages()
├── errors.py                # + InvalidRequirementError, TaskPlanningError
├── coder_agent.py           # internal only: uses invoke_model instead of _invoke_model; API unchanged
├── schemas.py               # unchanged (CoderResult etc. reused)
└── state.py                 # unchanged (CoderState)

orchestration/
├── __init__.py              # NEW (replaces gitkeep)
├── protocol.py              # NEW: TechnicalSpecification, Requirement, AcceptanceCriterion,
│                            #      PlannedTask, SpecificationDraft, TaskListDraft,
│                            #      TaskHandoff, SpecificationContext, TaskReport, TaskRecord,
│                            #      TeamOutcome, TeamResult, enums, build_handoff(), task_status_for()
├── state.py                 # NEW: TeamState (TypedDict)
└── team_graph.py            # NEW: run_dev_team(), build_team_graph(), dispatch/coder/record/
                             #      final_run/finalize nodes, routing, recursion limit, __main__ CLI

memory/semantic_memory.py    # MemoryRecord.kind docstring: + requirement, specification

tests/
├── unit/
│   ├── test_llm.py               # NEW: invoke_model wraps errors, passes CoderAgentError through
│   ├── test_protocol_models.py   # NEW: every FR-004 validation rule
│   ├── test_pm_agent.py          # NEW: PM node writes non-empty, schema-valid task list; consolidation
│   ├── test_handoff_protocol.py  # NEW: build_handoff, JSON round trip, status rule
│   └── test_team_graph.py        # NEW: scripted end-to-end handoff loop, failure stop, outcome
└── integration/
    ├── test_smoke_coder_agent.py # unchanged
    └── test_smoke_team.py        # NEW: smoke test for the two-agent system

README.md                    # + team overview, system diagram above, run command, new decisions
Dockerfile / docker-compose.yml  # unchanged: the default `pytest -m smoke -v` already picks up the new smoke test
```

**Structure Decision**: Single Python project, using the repo's existing top-level packages.
`orchestration/` holds the code that belongs to neither agent alone: the shared state, the
protocol and the team graph. `agents/` holds each agent's own logic.

## Complexity Tracking

No constitution violations to justify.
