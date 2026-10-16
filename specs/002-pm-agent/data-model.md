# Data Model: PM Agent and PM-to-Coder Handoff

All models are Pydantic v2 with `extra="forbid"` (the `_StrictModel` base from `agents/schemas.py`),
unless marked as a `TypedDict`. Models the Coder agent already has (`CoderResult`,
`GeneratedFile`, `ExecutionResult` and others) are reused unchanged; see
[001 data-model.md](../001-coder-agent/data-model.md).

New models live in `orchestration/protocol.py` (specification, tasks, handoff, report, result) and
`orchestration/state.py` (`TeamState`).

## Specification (written by the PM agent)

### TechnicalSpecification

| Field | Type | Rules |
|-------|------|-------|
| `name` | `str` | Not blank. Short name of what is being built. |
| `description` | `str` | Not blank. What it is and who it's for, in 1–3 sentences. |
| `requirements` | `list[Requirement]` | At least 1. IDs unique. |
| `acceptance_criteria` | `list[AcceptanceCriterion]` | At least 1. IDs unique. Each `requirement_id` names a real requirement. |
| `assumptions` | `list[str]` | May be empty. |
| `out_of_scope` | `list[str]` | May be empty. |
| `tasks` | `list[PlannedTask]` | At least 1. See the cross-field rules below. **No maximum in the schema** ([research R5](research.md#r5-pm-model-calls-and-their-structured-outputs)): the count limit is enforced by consolidation. |

The ID patterns below are enforced by Pydantic after parsing. For the model they're advisory
only: the structured-output API doesn't support `pattern`, so the SDK moves it into the field's
description ([research R5](research.md#r5-pm-model-calls-and-their-structured-outputs)).

Cross-field rules (validators; failures raise, constitution Principle II):

- Task IDs are unique.
- Each task's `depends_on` names only tasks earlier in the list. A dependency on an unknown task,
  on itself or on a later task is rejected.
- Each task's `covers` is non-empty and names only real requirement IDs.
- Every requirement is in at least one task's `covers` (spec FR-004, SC-005).

### Requirement

| Field | Type | Rules |
|-------|------|-------|
| `id` | `str` | Matches `R<number>`, for example `R1`. |
| `statement` | `str` | Not blank. One testable "MUST" statement. |

### AcceptanceCriterion

| Field | Type | Rules |
|-------|------|-------|
| `id` | `str` | Matches `AC<number>`. |
| `requirement_id` | `str` | A real requirement ID. |
| `text` | `str` | Not blank. A checkable condition. |

### PlannedTask

| Field | Type | Rules |
|-------|------|-------|
| `id` | `str` | Matches `T<number>`. |
| `title` | `str` | Not blank. |
| `description` | `str` | Not blank. What to build or change in this task. |
| `acceptance_criteria` | `list[str]` | At least 1. Task-level "done" conditions. |
| `priority` | `TaskPriority` | `high`, `medium` or `low`. Describes importance; it doesn't change order ([research R3](research.md#r3-the-handoff-protocol-a-current_handoff-state-key-holding-a-taskhandoff)). |
| `covers` | `list[str]` | At least 1. Requirement IDs this task delivers. |
| `depends_on` | `list[str]` | Earlier task IDs. May be empty. |

## PM model-call outputs (not returned to callers)

### SpecificationDraft (output of the `specify` call)

| Field | Type | Rules |
|-------|------|-------|
| `is_software_requirement` | `bool` | True only for a software request that can be built as a standard-library Python program (spec FR-012). |
| `decline_reason` | `str \| None` | Required and not blank when `is_software_requirement` is false. |
| `specification` | `TechnicalSpecification \| None` | Required when `is_software_requirement` is true; must be `None` when it's false. |

### TaskListDraft (output of the `consolidate` call)

| Field | Type | Rules |
|-------|------|-------|
| `tasks` | `list[PlannedTask]` | Replaces `specification.tasks`. The merged specification is re-validated, so coverage and dependency rules still hold. |

## Handoff protocol

Both messages serialize with `model_dump_json()` and load with `model_validate_json()`. Their JSON
Schemas and examples are in [contracts/handoff-protocol.md](contracts/handoff-protocol.md).

### TaskHandoff (PM side → Coder agent)

| Field | Type | Rules |
|-------|------|-------|
| `protocol_version` | `Literal["1"]` | Bumped on any breaking change. |
| `run_id` | `str` | The team run's ID. |
| `task_id` | `str` | A task ID from the specification. |
| `title` | `str` | Copied from the task. |
| `description` | `str` | Copied from the task. |
| `acceptance_criteria` | `list[str]` | Copied from the task. At least 1. |
| `priority` | `TaskPriority` | Copied from the task. |
| `depends_on` | `list[str]` | Copied from the task. |
| `context` | `SpecificationContext` | See below. |
| `workspace_files` | `list[str]` | Relative paths already in the shared workspace when the task is handed off. |

### SpecificationContext

| Field | Type | Rules |
|-------|------|-------|
| `name` | `str` | The spec's name. |
| `description` | `str` | The spec's description. |
| `out_of_scope` | `list[str]` | The spec's out-of-scope items. |
| `requirements` | `list[Requirement]` | **Only** the requirements in the task's `covers` (spec FR-005). |
| `acceptance_criteria` | `list[AcceptanceCriterion]` | **Only** the criteria whose `requirement_id` is in `covers`. |

Built by `build_handoff(specification, task, run_id, workspace_files)`, a pure function that can
be unit-tested without a model.

### TaskReport (Coder agent → shared state)

| Field | Type | Rules |
|-------|------|-------|
| `protocol_version` | `Literal["1"]` | |
| `task_id` | `str` | Must equal the handoff's `task_id`. |
| `status` | `TaskStatus` | `completed` or `failed` only, set by the rule in [research R8](research.md#r8-task-status-outcome-and-the-final-run). |
| `coder_result` | `CoderResult` | The Coder agent's unchanged result. |

## Shared state

### TaskRecord (one entry per task in `TeamState.tasks`)

| Field | Type | Rules |
|-------|------|-------|
| `task` | `PlannedTask` | |
| `status` | `TaskStatus` | Starts as `not_started`. |
| `handoff` | `TaskHandoff \| None` | Set when the task is handed off. |
| `report` | `TaskReport \| None` | Set when the Coder agent reports. Required when the status is `completed` or `failed`. |

### TeamState (LangGraph `TypedDict`, `total=False`)

| Key | Type | Written by | Read by |
|-----|------|-----------|---------|
| `run_id` | `str` | caller | all nodes |
| `requirement` | `str` | caller | PM nodes |
| `specification` | `TechnicalSpecification \| None` | `specify`, `consolidate` | `dispatch_task`, `finalize` |
| `decline_reason` | `str \| None` | `specify` | `finalize` |
| `consolidation_attempts` | `int` | `specify` (sets 0), `consolidate` (+1) | routing |
| `tasks` | `list[TaskRecord]` | `specify`, `consolidate`, `dispatch_task`, `record_report` | routing, `dispatch_task`, `finalize` |
| `current_handoff` | `TaskHandoff \| None` | `dispatch_task` (set), `record_report` (clears) | `coder` |
| `last_report` | `TaskReport \| None` | `coder` | `record_report` |
| `code` | `list[GeneratedFile]` | `record_report`, `final_run` | `finalize` |
| `final_execution` | `ExecutionResult \| None` | `final_run` | `finalize` |
| `result` | `TeamResult` | `finalize` | caller |

`current_handoff` being set is the "a task is ready" signal ([research R3](research.md#r3-the-handoff-protocol-a-current_handoff-state-key-holding-a-taskhandoff)).
`code` is the workspace snapshot taken after each task. Because all tasks share one workspace, it
holds everything written so far.

## Result returned to the caller

### TeamResult

| Field | Type | Rules |
|-------|------|-------|
| `specification` | `TechnicalSpecification \| None` | `None` only when `outcome.status` is `declined`. |
| `tasks` | `list[TaskRecord]` | Empty only when declined. |
| `code` | `list[GeneratedFile]` | Every file in the shared workspace at the end. |
| `execution_result` | `ExecutionResult` | The final run (spec FR-016). `not_run` when declined or when there's no entry point. |
| `outcome` | `TeamOutcome` | |

Cross-field rules:

- `completed` requires every task to be `completed` and `execution_result.status` to be neither
  `failed` nor `timed_out`.
- `declined` requires no tasks, no code and a `not_run` execution result.
- `failed` requires at least one `failed` task, or a final run that failed or timed out.

### TeamOutcome

| Field | Type | Rules |
|-------|------|-------|
| `status` | `OutcomeStatus` | `completed`, `failed` or `declined`. |
| `reason` | `str` | Not blank. For `failed`, it names the failed task ID or "final run". |

### Enums

- `TaskPriority`: `high`, `medium`, `low`
- `TaskStatus`: `not_started`, `in_progress`, `completed`, `failed`
- `OutcomeStatus`: `completed`, `failed`, `declined`

## State transitions

```text
Task:  not_started ──dispatch_task──► in_progress ──record_report──► completed
                                                        └─────────► failed
       (tasks after a failed task stay not_started)

Run:   specify ─┬─ declined ──────────────────────────────────────► finalize (declined)
                ├─ tasks > MAX_TASKS ─► consolidate ─┐ (at most MAX_CONSOLIDATION_ATTEMPTS)
                │                         ▲──────────┘   still too many → TaskPlanningError
                └─ tasks ≤ MAX_TASKS ─► dispatch_task ─► coder ─► record_report ─┐
                                              ▲                                   │
                                              └──── next not_started task ────────┤
                                                    task failed / none left ──────┴► final_run ─► finalize
```

## Memory records (additions)

`MemoryRecord.kind` gains two values:

- `requirement`: the requirement text.
- `specification`: the spec's name, its description, and its task IDs and titles.

The PM agent writes them after `specify`, and after each `consolidate` (for the updated task
list). Coder records for a task use `run_id = "<team run_id>:<task_id>"`.
