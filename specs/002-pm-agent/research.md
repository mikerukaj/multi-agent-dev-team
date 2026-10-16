# Research: PM Agent and PM-to-Coder Handoff

Phase 0 decisions for [plan.md](plan.md). Each entry gives the decision, why, and what else was
considered. Decisions from [001 research](../001-coder-agent/research.md) still apply unless an
entry here says otherwise.

## R1. One graph for both agents

- **Decision**: Build one LangGraph `StateGraph` over a shared `TeamState`, the "team graph". The
  PM agent's work is a set of nodes in it. The Coder agent's existing compiled graph
  (`build_coder_graph`) runs inside the team graph's `coder` node as a subgraph, called once per
  task in the same process. Nothing runs in a separate process or thread.
- **Rationale**: The user input requires one orchestration graph with no separate processes. The
  Coder graph keeps its own `CoderState` (messages, ReAct counters), which the PM side must not see
  or change. LangGraph's "call a subgraph from a node" pattern is designed for parent and child
  graphs with different state schemas: the node maps the handoff into a `CoderState`, invokes the
  child graph, and maps its `CoderResult` back into `TeamState`. Reusing `build_coder_graph`
  unchanged keeps FR-013, so the Coder-only API and smoke test don't move.
- **Alternatives considered**:
  - *Add the Coder graph as a node directly, with a shared schema*: this would need `CoderState`
    and `TeamState` to share keys such as `messages` and `iteration`, which mixes the two agents'
    private working state and breaks the Coder-only graph.
  - *Flatten the Coder nodes into the team graph*: duplicates the Coder wiring and drops the
    tested `build_coder_graph`.
  - *Call `run_coder_agent` from a node*: it insists on an empty workspace (FR-003 of 001), so
    task 2 could not see task 1's files.

## R2. Shared state: a `TypedDict` whose values are Pydantic models

- **Decision**: `TeamState` is a `TypedDict` (`total=False`), the same style as `CoderState`. Every
  value is a typed field: plain strings and ints, or Pydantic models from
  `orchestration/protocol.py` (`TechnicalSpecification`, `TaskRecord`, `TaskHandoff`,
  `TaskReport`, `GeneratedFile`, `ExecutionResult`, `TeamOutcome`). No field holds an untyped
  `dict`. Required keys from the user input:

  | User input | `TeamState` key |
  |------------|-----------------|
  | original requirement | `requirement` |
  | technical spec | `specification` |
  | task list and per-task status | `tasks: list[TaskRecord]` (each record has `status`) |
  | accumulated code output | `code: list[GeneratedFile]` |

- **Rationale**: LangGraph's native state type is a `TypedDict`. Pydantic values give the
  validation constitution Principle II requires before anything enters state. Nodes return
  partial updates, which is how LangGraph writes to state. They aren't ad-hoc dictionaries because
  every key they set is declared on `TeamState`.
- **Alternatives considered**: A Pydantic model as the graph state. It works, but LangGraph
  re-validates the whole model on every update, and it would differ from `CoderState` for no
  benefit.

## R3. The handoff protocol: a `current_handoff` state key holding a `TaskHandoff`

- **Decision**: The `dispatch_task` node writes the next task's `TaskHandoff` to
  `TeamState.current_handoff`. A non-empty `current_handoff` is the signal that a task is ready
  for the Coder agent. The `coder` node reads it, runs the task, and returns a `TaskReport`. The
  `record_report` node stores the report on the task's `TaskRecord`, updates statuses and `code`,
  and clears `current_handoff` back to `None`.
  - `TaskHandoff` contains `protocol_version`, `run_id`, `task_id`, `title`, `description`,
    `acceptance_criteria`, `priority`, `depends_on`, a `SpecificationContext` (spec name,
    description, out-of-scope items, and only the covered requirements and their acceptance
    criteria, per spec FR-005), and `workspace_files` (the paths already in the workspace).
  - Both `TaskHandoff` and `TaskReport` are Pydantic models with `extra="forbid"`. They serialize
    with `model_dump_json()` and load with `model_validate_json()`. Their JSON Schemas are in
    [contracts/handoff-protocol.md](contracts/handoff-protocol.md).
- **Rationale**: A state key is the user's suggested mechanism, and it keeps the handoff visible
  in graph state for debugging (spec User Story 2). Writing it to state first, then reading it in
  the next node, means the Coder agent only ever sees a validated message (FR-007).
  `workspace_files` is included because the Coder agent's tools can read and write files but
  can't list them, so without it a later task couldn't find the earlier tasks' files.
- **Alternatives considered**:
  - *A message in a shared `messages` list*: mixes protocol traffic with LLM conversation and needs
    parsing to read it back.
  - *Passing the whole specification*: rejected in clarification Q5, because it costs more tokens
    on every Coder round.

## R4. How a handoff becomes Coder agent input

- **Decision**: The `coder` node renders the `TaskHandoff` into the Coder agent's existing `task`
  string with `HANDOFF_TASK_TEMPLATE` in `agents/prompts.py`. The template lists the task, its
  acceptance criteria, the specification context, and the existing workspace files. The Coder
  graph's `run_id` is `<team run_id>:<task_id>`, so memory records stay traceable to the run.
- **Rationale**: The Coder agent's whole pipeline (plan, ReAct, finalize, memory retrieval) is
  keyed on `state["task"]`. Rendering into it means no change to the Coder agent's code. The
  structured `TaskHandoff` remains the contract, and the rendered text is just how it's shown to
  the model.
- **Alternatives considered**: Adding a `handoff` key to `CoderState` and teaching the Coder
  prompts to read it. That's more change for the same model-visible text.

## R5. PM model calls and their structured outputs

- **Decision**: The PM agent makes one structured call, `specify`, which returns a
  `SpecificationDraft`. The draft contains `is_software_requirement`, `decline_reason`, and
  `specification: TechnicalSpecification | None`, and the specification includes its tasks. Only
  when the task count is too high (R6) does the PM agent make a second structured call,
  `consolidate`, which returns a `TaskListDraft`.
  - Both calls use `with_structured_output(..., method="json_schema")`, the same as the Coder
    agent. Sonnet 5.5 rejects forced tool choice; see the README's implementation decisions.
  - The schemas use only features the API supports. `anthropic.transform_schema`, which
    `langchain-anthropic` calls, removes constraints the API can't enforce. Pydantic validators
    check them, and everything else, after parsing.
  - The task-count limit is deliberately **not** a schema or validator constraint, so that an
    over-long list reaches the consolidation step instead of failing to parse.
  - The ID `pattern`s (`^R\d+$`, `^AC\d+$`, `^T\d+$`) are advisory to the model.
    `transform_schema` doesn't send `pattern` as a constraint; it moves it into the field's
    description. Pydantic enforces the patterns after parsing. The PM prompts state the ID format
    explicitly so the model gets it right, and a wrong ID fails the run under the no-retry rule in
    R7.
- **Rationale**: One call for the spec and tasks together is the cheapest path for a normal
  requirement: 1 PM call, then the Coder agent's usual 3–5 calls per task. The user is
  cost-sensitive, which is why the project uses Sonnet. Producing the spec and its tasks together
  also lets the model keep task coverage consistent with the requirements it just wrote.
- **Alternatives considered**: Separate `write_spec` and `split_tasks` calls. That's one extra
  call on every run, with no quality need shown yet.

## R6. Loop prevention: consolidating an over-long task list

- **Decision**:
  - Constants in `config.py`: `MAX_TASKS = 8` and `MAX_CONSOLIDATION_ATTEMPTS = 2`.
  - After `specify`, the `check_tasks` routing sends the run to `consolidate` when
    `len(tasks) > MAX_TASKS`. `consolidate` asks the model to merge the tasks into at most
    `MAX_TASKS`, keeping every requirement covered, and increments `consolidation_attempts`.
  - Routing then checks again. If the list is still over the limit after
    `MAX_CONSOLIDATION_ATTEMPTS`, the run raises `TaskPlanningError` before any handoff (spec
    FR-004a).
  - The team graph's `recursion_limit` is derived from these constants plus `MAX_TASKS`, the same
    way `RECURSION_LIMIT` is derived in `coder_agent.py`, so the graph can't loop without bound.
- **Rationale**: This is the user input's "consolidate before proceeding" rule. The attempt cap
  and the derived recursion limit guarantee the loop ends.
- **Alternatives considered**:
  - *Truncate to the first 8 tasks*: silently drops requirements and breaks coverage (FR-004).
  - *Reject immediately*: this was the original spec, which the user input replaced.

## R7. What gets checked, and where

- **Decision**: Checks live in Pydantic validators on `TechnicalSpecification`, so they run on
  every parse, both `specify` and `consolidate`:
  - task IDs and requirement IDs are unique;
  - every `depends_on` names an earlier task;
  - every `covers` names a real requirement;
  - every requirement is covered by at least one task;
  - every acceptance criterion names a real requirement;
  - at least one task, one requirement and one acceptance criterion.

  A model answer that fails these is raised as `LLMServiceError`, with the PM stage named in the
  message. It isn't retried with a re-prompt.
- **Rationale**: Constitution Principle II: validation failures MUST raise, not be coerced. Using
  the same validators for both calls means a consolidated list can't break coverage.
- **Alternatives considered**: Re-prompting the model to fix a bad task list. That's more loop
  machinery than the spec asks for, and it could be added later if real runs need it.

## R8. Task status, outcome and the final run

- **Decision**:
  - `TaskStatus`: `not_started → in_progress → completed | failed`.
  - `record_report` sets the status from the `CoderResult`, following spec FR-010:
    - **completed** when `execution_result.success`, or when `status == not_run` and
      `stop_reason == completed`;
    - **failed** otherwise, which covers a failed or timed-out run, `iteration_limit`,
      `revision_limit` and `rejected`.
  - On a failure, routing goes straight to `final_run` and the remaining tasks stay
    `not_started` (FR-010a).
  - `final_run` calls the existing `tools.exec_python.run_python_file` on `ENTRYPOINT`. That
    reuses the same isolation and timeout and makes no model call (FR-016). If there's no
    entry point, it records `ExecutionResult.not_run()`.
  - `finalize` builds the `TeamOutcome`: `completed`, `failed` (the reason names the failed task
    or the final run), or `declined`.
- **Rationale**: Directly follows clarifications Q2–Q4, and reuses the Coder agent's runner rather
  than adding a second one.

## R9. Memory for the PM agent

- **Decision**: The PM agent uses the same `SemanticMemory` (the same Chroma collection,
  `coder_agent_memory`) and the same `AgentDependencies` object as the Coder agent.
  - The memory-retrieval part of `agents/context.py` moves into a shared helper,
    `retrieve_past_context(query, dependencies)`. `build_llm_messages` (Coder) and a new
    `build_pm_messages` (PM) both call it, so "retrieve before every LLM call" holds for both
    agents (spec FR-015).
  - The PM agent stores two new record kinds: `requirement` and `specification`. The
    specification record holds the spec's name, description and task titles.
- **Rationale**: The constitution requires all memory to go through Chroma. Keeping the existing
  collection name avoids leaving developers' existing memory behind; the name is historical.
  Extracting the helper avoids copying the retrieval logic (Principle I).
- **Alternatives considered**: A separate `pm_agent_memory` collection. Two stores to wipe and
  inspect, with no benefit shown.

## R10. Progress output and errors

- **Decision**:
  - Each team node logs one `INFO` line through `logging` to stderr. Examples: "PM: specification
    'X' with 3 tasks", "Task T2 handed off", "Task T2 completed", "Final run succeeded". This
    gives the CLI visible progress during a run that can take several minutes. It settles the
    observability item deferred in clarification.
  - New errors subclass the existing `CoderAgentError`, so callers catching it still catch
    everything:
    - `InvalidRequirementError`, for an empty requirement;
    - `TaskPlanningError`, for a task list still over the limit after consolidation.
  - LLM failures in PM nodes raise `LLMServiceError` with the prefix `"PM <stage> failed: "`.
    Failures inside a task raise with the prefix `"Task <id> failed: "` (spec edge case: name the
    stage).
  - All model calls, and the Coder subgraph call, go through one shared helper:
    `agents/llm.py:invoke_model(runnable, payload, stage, config)`. It replaces the Coder agent's
    private `_invoke_model`. Without it, the same "wrap failures as `LLMServiceError`" logic would
    appear in four places, and constitution Principle I requires extracting logic duplicated in
    three or more places. The default stage, `"Model call"`, keeps the Coder agent's existing
    error message the same.
- **Rationale**: Uses the existing logging setup and error hierarchy; adds no dependencies.

## R11. Testing

- **Decision**:
  - **Unit tests** (offline, `ScriptedChatModel`):
    - `test_pm_agent.py`: after the PM `specify` node runs, the returned state update has a
      non-empty `tasks` list in which every item validates as `TaskRecord` with status
      `not_started`, and `specification` validates. This is the test the user input requires.
      Also covers: declined requirements, the validators from R7, and consolidation from 9 tasks
      down to at most 8, including the attempt limit.
    - `test_protocol_models.py`: one test per `TechnicalSpecification` and `SpecificationDraft`
      validation rule from R7 (spec FR-004).
    - `test_llm.py`: the shared `invoke_model` helper.
    - `test_handoff_protocol.py`: a `TaskHandoff` holds only the covered requirements, has the
      `priority` field, and survives a `model_dump_json()` → `model_validate_json()` round trip.
    - `test_team_graph.py`: a scripted two-task run through the compiled team graph checks the
      handoff order, the per-task status updates, `code` after each task, stopping after a failed
      task, the final run, and the outcome values.
  - **Smoke test**: `tests/integration/test_smoke_team.py` runs the spec FR-014 requirement through
    `run_dev_team` and skips with a reason when there's no key. The Coder-only smoke test stays
    unchanged (SC-007).
- **Rationale**: Matches the 001 strategy: offline unit tests, and paid smoke tests as the merge
  gate.
