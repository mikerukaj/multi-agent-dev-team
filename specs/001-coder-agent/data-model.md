# Data Model: Coder Agent

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-10-09

All output models are Pydantic v2 models with `extra="forbid"` (Principle II). Limits referenced
below (`MAX_ITERATIONS`, `MAX_REVISIONS`, etc.) live in `config.py` (Principle V).

## Output models (returned to the caller)

### CoderResult

The single structured result (spec FR-007). Exactly four top-level fields.

| Field | Type | Rules |
|-------|------|-------|
| `code` | `list[GeneratedFile]` | Every file in the workspace at finalize time. MAY be empty only when `plan.stop_reason == "rejected"`. |
| `explanation` | `str` | Non-empty after stripping whitespace. |
| `plan` | `ExecutionPlan` | Required. |
| `execution_result` | `ExecutionResult` | Required. |

Cross-field rule: if `plan.stop_reason == "rejected"`, then `code == []` and
`execution_result.status == "not_run"`.

### GeneratedFile

| Field | Type | Rules |
|-------|------|-------|
| `path` | `str` | Relative POSIX path inside the workspace; no `..`, not absolute. |
| `content` | `str` | Full file contents as written to disk. |

### ExecutionPlan

| Field | Type | Rules |
|-------|------|-------|
| `steps` | `list[str]` | At least 1 item. The ordered plan made before coding. |
| `trace` | `list[ReActStep]` | Ordered by `iteration`. Empty only when rejected. |
| `iterations` | `int` | `0 ≤ iterations ≤ MAX_ITERATIONS` (10). |
| `revision_attempts` | `int` | `0 ≤ revision_attempts ≤ MAX_REVISIONS` (3). The number of `exec_python` runs the agent made *after* its first failed run. The extra run `finalize` may do is not counted. |
| `stop_reason` | `StopReason` | See enum below. |

### ReActStep

One Thought → Action → Observation round.

| Field | Type | Rules |
|-------|------|-------|
| `iteration` | `int` | 1-based. |
| `thought` | `str` | The model's reasoning text for this round. |
| `action` | `str \| None` | Tool name (`read_file`, `write_file`, `exec_python`), or `None` on the final round. |
| `action_input` | `dict` | Tool arguments. `write_file` content is replaced by a size note to keep the trace small. |
| `observation` | `str \| None` | Tool result text, truncated to `MAX_OBSERVATION_CHARS`. |

A round with several tool calls produces one `ReActStep` per tool call, all with the same
`iteration`. A closing step with `action = None` is added only when `stop_reason == "completed"`
(the model's last message had no tool calls). Runs stopped by a limit end on their last tool step.

### PlanDecision (structured output of the `plan` LLM call; not returned)

| Field | Type | Rules |
|-------|------|-------|
| `steps` | `list[str]` | At least 1 item, so an empty plan fails at once rather than in `finalize`. |
| `is_coding_task` | `bool` | |
| `rejection_reason` | `str \| None` | Required (non-blank) when `is_coding_task` is false. |

### ExplanationDraft (structured output of the `finalize` LLM call; not returned)

| Field | Type | Rules |
|-------|------|-------|
| `explanation` | `str` | Non-blank. |

### ExecutionResult

| Field | Type | Rules |
|-------|------|-------|
| `status` | `ExecutionStatus` | See enum below. |
| `success` | `bool` | MUST equal `status == "succeeded"` (validator). |
| `exit_code` | `int \| None` | `None` when `timed_out` or `not_run`. |
| `stdout` | `str` | Truncated to `MAX_OUTPUT_CHARS`. |
| `stderr` | `str` | Truncated to `MAX_OUTPUT_CHARS`. |
| `truncated` | `bool` | True if either stream was cut. |
| `duration_seconds` | `float \| None` | `None` when `not_run`. |
| `entrypoint` | `str \| None` | Workspace-relative path that was run. |

### Enums

- **ExecutionStatus**: `succeeded` · `failed` · `timed_out` · `not_run`
- **StopReason**: `completed` (model stopped calling tools) · `iteration_limit` (hit 10) ·
  `revision_limit` (initial run + 3 revisions all failed) · `rejected` (not a coding task)

## Internal state (not returned)

### CoderState (LangGraph graph state)

| Field | Type | Notes |
|-------|------|-------|
| `run_id` | `str` | UUID per invocation; used as Chroma metadata. |
| `task` | `str` | Validated non-empty task text. |
| `plan_steps` | `list[str]` | From the `plan` node. |
| `is_coding_task` | `bool` | From the `plan` node. |
| `rejection_reason` | `str \| None` | Set when not a coding task. |
| `messages` | `list[BaseMessage]` | Full ReAct message history (the buffer windows this for prompts). |
| `trace` | `list[ReActStep]` | Built as rounds complete. |
| `iteration` | `int` | Incremented once per `reason` call. |
| `first_failure_seen` | `bool` | Set when an `exec_python` run first ends `failed` or `timed_out`. |
| `revision_attempts` | `int` | Incremented for each `exec_python` run after `first_failure_seen` was already set. |
| `last_execution` | `ExecutionResult \| None` | Most recent `exec_python` result. |
| `files_changed_since_run` | `bool` | Set by `write_file`; cleared by `exec_python`. |
| `stop_reason` | `StopReason \| None` | Set by routing. |

The workspace path is not stored in state; the graph nodes are built for one workspace
(`build_coder_graph(dependencies, workspace)`). `finalize` adds a `result` key holding the
validated `CoderResult`.

### State transitions

```text
START → plan
plan → finalize                      if not is_coding_task          (stop_reason = rejected)
plan → reason
reason → act                         if the model made tool calls
reason → finalize                    if no tool calls               (stop_reason = completed)
act → finalize                       if revision_attempts ≥ MAX_REVISIONS and the last run failed
                                                                    (stop_reason = revision_limit)
act → finalize                       if revision_attempts ≥ MAX_REVISIONS and the last run succeeded
                                                                    (stop_reason = completed)
act → finalize                       if iteration ≥ MAX_ITERATIONS  (stop_reason = iteration_limit)
act → reason                         otherwise
finalize → END
```

`finalize` runs the entrypoint itself when `last_execution is None` or
`files_changed_since_run` is true (research R9).

### ConversationBuffer (memory layer 1)

| Field | Type | Notes |
|-------|------|-------|
| `max_turns` | `int` | `MEMORY_WINDOW_TURNS`, default 6. |

`window(messages) -> list[BaseMessage]` returns the last `max_turns` turns. A turn is one
`AIMessage` plus the `ToolMessage`s that answer its tool calls; turns are never split. The system
prompt, task and plan are added separately and are always present.

### MemoryRecord (memory layer 2, one Chroma document)

| Field | Type | Notes |
|-------|------|-------|
| `id` | `str` | `{run_id}:{iteration}:{kind}:{n}` |
| `document` | `str` | The text that is embedded. |
| `metadata.run_id` | `str` | |
| `metadata.kind` | `str` | `task` · `plan` · `thought` · `observation` · `result` |
| `metadata.iteration` | `int` | 0 for `task`/`plan`/`result`. |
| `metadata.created_at` | `str` | ISO-8601 UTC. |

Collection: `coder_agent_memory`. Retrieval returns at most `MEMORY_TOP_K` (default 4)
records with distance ≤ `MEMORY_MAX_DISTANCE`.
