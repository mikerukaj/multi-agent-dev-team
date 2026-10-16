---

description: "Task list for the PM agent and PM-to-Coder handoff"
---

# Tasks: PM Agent and PM-to-Coder Handoff

**Input**: Design documents from `/specs/002-pm-agent/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Included. The spec requires a smoke test (FR-014), and the `/speckit-plan` input asks
for tests covering the PM → Coder handoff. In each story, write the test tasks first and confirm
they fail before implementing.

**Organization**: Tasks are grouped by user story, so each story can be implemented and tested on
its own.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: Which user story the task belongs to (US1, US2, US3)

## Path Conventions

Single Python project at the repository root: `agents/`, `orchestration/`, `memory/`, `tools/`,
`tests/`, as described in [plan.md › Project Structure](plan.md#source-code-repository-root).

## Conventions for every task

- Follow the existing code style: type hints and a docstring on every public function, class and
  graph node; no magic values; functions of about 40 lines or less with at most 4 parameters
  (constitution Principle I).
- New Pydantic models subclass `_StrictModel` from `agents/schemas.py` (`extra="forbid"`).
- Don't change the Coder agent's public API (`run_coder_agent`, `build_coder_graph`, the CLI),
  its schemas (`agents/schemas.py`), its state (`agents/state.py`) or
  `tests/integration/test_smoke_coder_agent.py` (spec FR-013, SC-007). Internal refactors of
  `agents/coder_agent.py` that keep its behavior, such as T005, are allowed.
- Every model call (and the Coder subgraph call) goes through the shared `invoke_model` helper
  from T005. Don't write another try/except that wraps model errors (constitution Principle I).
- Unit tests use the existing fixtures in `tests/conftest.py`: `settings`, `workspace`,
  `make_dependencies` (a `ScriptedChatModel` with `responses` for tool-bound calls and
  `structured` for `with_structured_output` calls, in call order), and `retrieve_spy`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Package layout, constants and errors that every later task imports.

- [X] T001 Replace the placeholder `orchestration/gitkeep` with `orchestration/__init__.py` containing a one-line module docstring ("Shared state, handoff protocol and the team graph that runs the PM and Coder agents.")
- [X] T002 [P] Add constants to `config.py` after `MAX_REVISIONS`, each with a docstring: `MAX_TASKS = 8` ("Most tasks the PM agent may hand off for one requirement; more triggers consolidation.") and `MAX_CONSOLIDATION_ATTEMPTS = 2` ("Most times the PM agent may consolidate an over-long task list before the run fails."). Change the module docstring's "for the Coder agent" to "for the agents" ([research R6](research.md#r6-loop-prevention-consolidating-an-over-long-task-list))
- [X] T003 [P] Add `InvalidRequirementError(CoderAgentError)` ("The requirement is empty or whitespace only. Raised before any work is done.") and `TaskPlanningError(CoderAgentError)` ("The task list is still longer than MAX_TASKS after MAX_CONSOLIDATION_ATTEMPTS consolidations.") to `agents/errors.py`, and update the module docstring to mention the PM agent ([contracts/team-api.md](contracts/team-api.md#run_dev_team))
- [X] T004 [P] In `memory/semantic_memory.py`, update the `MemoryRecord.kind` docstring to "One of: task, plan, thought, observation, result, requirement, specification." ([data-model.md › Memory records](data-model.md#memory-records-additions))

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The shared model-call helper, the protocol models, the shared state, the prompts and
the shared memory helper.
Every user story depends on these.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T005 [P] Create `agents/llm.py` with `invoke_model(runnable: Runnable, payload: Any, stage: str = "Model call", config: RunnableConfig | None = None) -> Any`. It calls `runnable.invoke(payload, config)`, re-raises `CoderAgentError` unchanged, and turns any other exception into `LLMServiceError(f"{stage} failed: {error}")`. In `agents/coder_agent.py`, delete the private `_invoke_model` and call `invoke_model` at its three call sites with the default stage, so the Coder agent's error message stays exactly `"Model call failed: ..."`. Add `tests/unit/test_llm.py`: a runnable that raises `RuntimeError` gives `LLMServiceError` with the stage prefix, a `CoderAgentError` passes through unchanged, and a successful call returns the value. Run `pytest tests/unit` to confirm the Coder tests still pass (constitution Principle I: shared helper, analysis C1)
- [X] T006 Create `orchestration/protocol.py` with the enums `TaskPriority` (`high`, `medium`, `low`), `TaskStatus` (`not_started`, `in_progress`, `completed`, `failed`) and `OutcomeStatus` (`completed`, `failed`, `declined`), all `StrEnum`, plus the constant `PROTOCOL_VERSION = "1"`
- [X] T007 In `orchestration/protocol.py`, add the specification models exactly as in [data-model.md › Specification](data-model.md#specification-written-by-the-pm-agent):
  - `Requirement` (`id` matching `^R\d+$`, `statement` not blank) and `AcceptanceCriterion` (`id` matching `^AC\d+$`, `requirement_id`, `text` not blank).
  - `PlannedTask` (`id` matching `^T\d+$`, `title`, `description`, `acceptance_criteria` with at least 1 item, `priority: TaskPriority`, `covers` with at least 1 item, `depends_on` defaulting to an empty list).
  - `TechnicalSpecification` with an `@model_validator(mode="after")` that raises `ValueError` with a specific message for each of these: duplicate requirement, criterion or task IDs; a criterion naming an unknown requirement; a task covering an unknown requirement; a `depends_on` naming an unknown, the same or a later task; a requirement covered by no task. The validator must **not** check the task count.
  - Give every field a `Field(description=...)`, because the descriptions are sent to the model in the JSON schema.
  - Use only `pattern`, `min_length` on lists and validators. No `max_length`, `ge` or `le` constraints ([research R5](research.md#r5-pm-model-calls-and-their-structured-outputs)). (depends on T006)
- [X] T008 In `orchestration/protocol.py`, add the PM model-call outputs `SpecificationDraft` (`is_software_requirement`, `decline_reason`, `specification`), with a validator requiring `decline_reason` exactly when the requirement is declined and `specification` exactly when it isn't, and `TaskListDraft` (`tasks: list[PlannedTask]` with at least 1 item), as in [data-model.md › PM model-call outputs](data-model.md#pm-model-call-outputs-not-returned-to-callers). (depends on T007)
- [X] T009 In `orchestration/protocol.py`, add the handoff and result models as in [data-model.md](data-model.md#handoff-protocol):
  - `SpecificationContext`.
  - `TaskHandoff`, with `protocol_version: Literal["1"] = PROTOCOL_VERSION`.
  - `TaskReport`, with `status` limited to `completed` or `failed` by a validator, and `coder_result: CoderResult` imported from `agents.schemas`.
  - `TaskRecord`, with a validator: `report` is required when the status is `completed` or `failed`, and `handoff` is required unless the status is `not_started`.
  - `TeamOutcome`, with a non-blank `reason`.
  - `TeamResult`, with the cross-field outcome rules from [data-model.md › TeamResult](data-model.md#teamresult).

  (depends on T008)
- [X] T010 [P] Create `orchestration/state.py` with `TeamState(TypedDict, total=False)` holding exactly the keys and types in [data-model.md › TeamState](data-model.md#teamstate-langgraph-typeddict-totalfalse): `run_id`, `requirement`, `specification`, `decline_reason`, `consolidation_attempts`, `tasks`, `current_handoff`, `last_report`, `code`, `final_execution`, `result`. Include a class docstring that names `current_handoff` as the "task ready" signal. (depends on T009)
- [X] T011 [P] Add the PM prompts to `agents/prompts.py` ([research R4–R6](research.md#r4-how-a-handoff-becomes-coder-agent-input)):
  - `PM_SYSTEM_PROMPT`: you are the PM agent; write a formal technical spec and an ordered task list for a Python standard-library program whose entry point is `ENTRYPOINT`; each task must produce or change Python code; use IDs R1.., AC1.., T1..; depend only on earlier tasks; cover every requirement; prefer the fewest tasks, at most `MAX_TASKS`.
  - `SPECIFY_PROMPT`: decide whether the requirement is a software request that can be built as a standard-library Python program. If it can't, decline it with a reason, and never substitute a different kind of program. For buildable software that needs something else (a web front end, a mobile app, third-party packages), the reason must say that only standard-library Python programs can be built (spec FR-012). Otherwise, fill in the specification.
  - `CONSOLIDATE_PROMPT`, with `{task_count}`, `{max_tasks}` and `{tasks_json}` placeholders: merge into at most `max_tasks` tasks, keep every requirement covered, and keep dependencies pointing to earlier tasks.
  - `REQUIREMENT_TEMPLATE`, with a `{requirement}` placeholder.
  - `HANDOFF_TASK_TEMPLATE`, which renders a `TaskHandoff` for the Coder agent: task ID and title, description, acceptance criteria, priority, the spec name and description, the covered requirements and criteria, out-of-scope items, and "Files already in the workspace (read them before changing them):" followed by `workspace_files`, or "(none)".
- [X] T012 Refactor `agents/context.py`:
  - Extract `retrieve_past_context(query: str, dependencies: AgentDependencies) -> list[str]`, which holds the `memory.retrieve` call and the debug log. `build_llm_messages` must call it, and its behavior must not change.
  - Add `build_pm_messages(state: TeamState, instruction: str, dependencies: AgentDependencies) -> list[BaseMessage]`. It calls `retrieve_past_context(state["requirement"], ...)` and returns `[SystemMessage(PM_SYSTEM_PROMPT + past context), HumanMessage(REQUIREMENT_TEMPLATE), HumanMessage(instruction)]`, reusing `PAST_CONTEXT_TEMPLATE` ([research R9](research.md#r9-memory-for-the-pm-agent)).

  (depends on T010, T011)
- [X] T013 [P] Add a `make_specification(task_count: int = 2) -> TechnicalSpecification` helper and a `specification_draft` fixture to `tests/conftest.py`. The helper returns a valid spec with requirements R1..Rn, one criterion per requirement, and tasks T1..Tn where Tk covers Rk and depends on Tk-1, each with `priority="high"`. The fixture returns `SpecificationDraft(is_software_requirement=True, specification=make_specification())`. (depends on T009)
- [X] T014 [P] Create `tests/unit/test_protocol_models.py` with one test per `TechnicalSpecification` and `SpecificationDraft` rule, each building a spec from `make_specification(3)` and changing one thing, then asserting `pydantic.ValidationError` with the rule's message (spec FR-004, edge cases):
  - duplicate requirement, criterion and task IDs;
  - a task depending on itself, on a later task, and on an unknown task;
  - a task covering an unknown requirement, and a task with empty `covers`;
  - an acceptance criterion naming an unknown requirement;
  - a requirement no task covers;
  - an empty task list, an empty requirement list, and an empty criteria list;
  - an ID that breaks its pattern (`Task1`, `Req1`);
  - nine tasks validate (the count is not a validator rule, research R6);
  - `SpecificationDraft` with `is_software_requirement=True` and no specification, and with `False` and a specification, both rejected.

  (depends on T009, T013)
- [X] T015 Add `build_pm_messages` tests to `tests/unit/test_context.py`: it calls `memory.retrieve` exactly once (use `retrieve_spy`), it puts past context in the system message when memory returns some, and the requirement text appears in the messages. Run the whole existing `tests/unit/test_context.py` and confirm it still passes. (depends on T012, T013)

**Checkpoint**: The foundation is ready, and `pytest tests/unit` passes.

---

## Phase 3: User Story 1 - Turn a high-level requirement into a specification and working code (Priority: P1) 🎯 MVP

**Goal**: A requirement goes through the PM agent (spec plus tasks, consolidated if there are more
than 8), every task is handed to the Coder agent in order in one shared workspace, progress is
written back after each task, the final run happens, and a validated `TeamResult` is returned.

**Independent Test**: The `test_team_graph.py` happy path and `test_smoke_team.py`. The result
has a spec, at least one task, a report for every task, the code, a successful final run that
printed a date and time, and outcome `completed`.

### Tests for User Story 1 ⚠️ (write first; they must fail)

- [X] T016 [P] [US1] Create `tests/unit/test_pm_agent.py` with `test_specify_writes_non_empty_task_list_to_shared_state` (the test the plan input requires):
  - Build `PMNodes(make_dependencies(structured=[specification_draft]))` and call `.specify({"run_id": "r1", "requirement": "Build an LA clock"})`.
  - Assert the returned update has `specification` as a valid `TechnicalSpecification`, and `tasks` as a non-empty list where every item validates with `TaskRecord.model_validate(item.model_dump())`, has `status == TaskStatus.NOT_STARTED`, and has `task.id` values matching the spec's tasks in order.
  - Assert `consolidation_attempts == 0`.
  - Also add `test_specify_retrieves_memory_first` (`retrieve_spy.calls == 1`) and `test_specify_stores_requirement_and_specification_records` (memory holds a `requirement` and a `specification` record for `r1`).
- [X] T017 [US1] Add consolidation tests to `tests/unit/test_pm_agent.py`, using `make_specification(9)`:
  - `consolidate` replaces the tasks with the `TaskListDraft` tasks and increments `consolidation_attempts`.
  - The routing function `route_after_planning` returns `"consolidate"` when there are 9 tasks and fewer than `MAX_CONSOLIDATION_ATTEMPTS` attempts, returns `"dispatch_task"` when there are at most 8 tasks, and raises `TaskPlanningError` when there are 9 tasks after `MAX_CONSOLIDATION_ATTEMPTS` attempts.
  - A consolidated list that leaves a requirement uncovered raises `LLMServiceError` whose message starts with `"PM consolidate failed:"`.
  - A scripted structured answer that fails to parse (a dict missing `tasks`) raises `LLMServiceError` whose message starts with `"PM consolidate failed:"` (spec edge case: name the stage).
- [X] T018 [P] [US1] Create `tests/unit/test_team_graph.py` with `test_two_task_run_hands_off_in_order_and_records_progress`:
  - Script one PM draft with 2 tasks (T1 writes `clock.py`, T2 writes `main.py` that imports it and prints a date and time).
  - For each task, script the Coder calls: a plan decision, `write_file` and `exec_python` tool-call messages using `tool_call_message`, a final message with no tool calls, and an explanation draft.
  - Run `build_team_graph(dependencies, workspace).invoke(...)` with the team recursion limit.
  - Assert:
    - both `TaskRecord`s are `completed`, each with a handoff and a report whose `task_id` matches;
    - T2's `handoff.workspace_files == ["clock.py"]`;
    - `result.code` has both files;
    - `result.execution_result.success`;
    - `result.outcome.status == "completed"`.
- [X] T019 [P] [US1] Create `tests/integration/test_smoke_team.py` exactly per [contracts/team-api.md › Smoke test contract](contracts/team-api.md#smoke-test-contract-constitution-principle-iii-spec-fr-014):
  - `@pytest.mark.smoke`, and skip with the reason `ANTHROPIC_API_KEY not set`.
  - `load_dotenv()` at import.
  - Build `AgentDependencies.from_settings(settings)` so the test uses the temporary Chroma folder.
  - Reuse the date and time regexes by importing `DATE_PATTERN` and `TIME_PATTERN` from `tests.integration.test_smoke_coder_agent`.

### Implementation for User Story 1

- [X] T020 [US1] In `orchestration/protocol.py`, add `build_handoff(specification, task, run_id, workspace_files) -> TaskHandoff`. It copies the task's fields and builds a `SpecificationContext` with only the requirements in `task.covers`, and only the criteria whose `requirement_id` is in `task.covers`. Also add `task_status_for(result: CoderResult) -> TaskStatus` implementing the status rule in [contracts/handoff-protocol.md › Status rule](contracts/handoff-protocol.md#status-rule-spec-fr-010).
- [X] T021 [US1] Create `agents/pm_agent.py` with `class PMNodes`, whose `__init__(self, dependencies)` stores the dependencies, and two methods:
  - `specify(self, state: TeamState) -> TeamState` calls `build_pm_messages(state, SPECIFY_PROMPT, ...)` and calls `invoke_model(llm.with_structured_output(SpecificationDraft, method="json_schema"), messages, "PM specify")`, so a failure raises `LLMServiceError("PM specify failed: ...")`. It stores `MemoryRecord`s of kind `requirement` and `specification`, logs `"PM: specification '%s' with %d tasks"` at INFO, and returns `specification`, `tasks` (one `TaskRecord(task=t, status=NOT_STARTED)` per task), `decline_reason=None` and `consolidation_attempts=0`.
  - `consolidate(self, state: TeamState) -> TeamState` uses `CONSOLIDATE_PROMPT` with the current tasks as JSON. It calls `invoke_model(llm.with_structured_output(TaskListDraft, method="json_schema"), messages, "PM consolidate")`, then rebuilds the spec with `specification.model_copy(update={"tasks": ...})` followed by `TechnicalSpecification.model_validate(...model_dump())`, so the R7 rules run again. A validation failure from that rebuild becomes `LLMServiceError("PM consolidate failed: ...")`. Raise it with `from error`; this isn't a model call, so there's no helper duplication. It stores an updated `specification` memory record and returns the new `specification`, the rebuilt `tasks`, and `consolidation_attempts + 1`.

  (depends on T005, T012, T020)
- [X] T022 [US1] Create `orchestration/team_graph.py` with the routing functions:
  - `route_after_planning(state) -> str`: returns `"consolidate"` while `len(tasks) > MAX_TASKS` and attempts are below `MAX_CONSOLIDATION_ATTEMPTS`; raises `TaskPlanningError` when the tasks are still over the limit and the attempts are used up; otherwise returns `"dispatch_task"`.
  - `route_after_record(state) -> str`: returns `"dispatch_task"` when a task is still `not_started`, otherwise `"final_run"`.
  - `TEAM_RECURSION_LIMIT`: derived from `MAX_CONSOLIDATION_ATTEMPTS` and `MAX_TASKS` (3 steps per task, plus specify, consolidations, final_run, finalize, plus headroom), with a docstring like `RECURSION_LIMIT` in `agents/coder_agent.py`.

  (depends on T010)
- [X] T023 [US1] In `orchestration/team_graph.py`, add `class _TeamNodes` with `__init__(self, dependencies, workspace)`. It creates `PMNodes(dependencies)` and compiles `self.coder_graph = build_coder_graph(dependencies, workspace)` once ([research R1](research.md#r1-one-graph-for-both-agents)). Give it these nodes:
  - `dispatch_task`: picks the first `not_started` task, builds its handoff with `build_handoff(..., [f.path for f in list_workspace_files(workspace)])`, sets the task to `in_progress` with the handoff on its record, sets `current_handoff`, and logs `"Task %s handed off"`.
  - `coder`: renders `HANDOFF_TASK_TEMPLATE` from `state["current_handoff"]` and invokes `self.coder_graph` with `{"run_id": f"{run_id}:{task_id}", "task": rendered, "messages": []}` and the Coder's `RECURSION_LIMIT`, through `invoke_model(self.coder_graph, coder_state, f"Task {task_id}", config)`. A `CoderAgentError` raised inside the Coder agent is caught once and re-raised as the same class with the prefix `f"Task {task_id} failed: "`, so the failing stage is named (spec edge case). It then returns `last_report=TaskReport(task_id=..., status=task_status_for(result), coder_result=result)`.
  - `record_report`: stores the report on the matching `TaskRecord`, sets its status, sets `code = list_workspace_files(workspace)`, clears `current_handoff` and `last_report` to `None`, and logs `"Task %s %s"` with the status.
  - `final_run`: if `workspace / ENTRYPOINT` exists, it calls `run_python_file(workspace, ENTRYPOINT, settings.exec_timeout_seconds, settings.max_output_chars)`, otherwise it uses `ExecutionResult.not_run()`. It stores `final_execution`, refreshes `code`, and logs the status. It makes no model call.
  - `finalize`: builds `TeamOutcome` (`completed` when every task is completed and the final run neither failed nor timed out; otherwise `failed`, with a reason naming the first failed task ID or "final run") and returns `result=TeamResult(...)`.

  (depends on T020, T021, T022)
- [X] T024 [US1] In `orchestration/team_graph.py`, add `build_team_graph(dependencies, workspace) -> CompiledStateGraph`:
  - nodes `specify`, `consolidate`, `dispatch_task`, `coder`, `record_report`, `final_run`, `finalize`;
  - edges `START→specify`;
  - conditional edges `specify→route_after_planning→[consolidate, dispatch_task]` and `consolidate→route_after_planning→[consolidate, dispatch_task]`;
  - `dispatch_task→coder→record_report`;
  - a conditional edge `record_report→route_after_record→[dispatch_task, final_run]`;
  - `final_run→finalize→END`.

  Add the docstring from [contracts/team-api.md › build_team_graph](contracts/team-api.md#build_team_graph). (depends on T023)
- [X] T025 [US1] In `orchestration/team_graph.py`, add `run_dev_team(requirement, workspace=None, *, dependencies=None) -> TeamResult`, mirroring `run_coder_agent`: make a `uuid4().hex` run ID, use `prepare_workspace` (which rejects a non-empty folder with `InvalidWorkspaceError`), build the default dependencies, invoke with `TEAM_RECURSION_LIMIT`, and return `final_state["result"]`. Also add `main(argv)` and `if __name__ == "__main__"` for the CLI in [contracts/team-api.md › CLI](contracts/team-api.md#cli): JSON on stdout, `logging.basicConfig` on stderr, and exit code 1 with `<ErrorName>: <message>` on `CoderAgentError`. (depends on T024)
- [X] T026 [US1] Run `pytest tests/unit` (T016–T018 must now pass) and `pytest -m smoke -v` with a key. `test_smoke_team` and the unchanged `test_smoke_coder_agent` must both pass. Fix any failures before moving on.

**Checkpoint**: The MVP works. The two-agent system turns the smoke requirement into a spec,
tasks, code and a successful final run.

---

## Phase 4: User Story 2 - Inspect the handoff between the agents (Priority: P2)

**Goal**: Every handoff and report is strictly structured, JSON-serializable, checked before it's
passed on, and kept side by side in the result.

**Independent Test**: `pytest tests/unit/test_handoff_protocol.py`, plus the inspection steps in
[quickstart.md](quickstart.md) step 5.

### Tests for User Story 2 ⚠️ (write first; they must fail)

- [X] T027 [P] [US2] Create `tests/unit/test_handoff_protocol.py`. Using `make_specification(3)` and its task T2, test:
  - `build_handoff` puts only R2 and its criterion in `context`, copies `priority`, `depends_on` and `acceptance_criteria`, and keeps `workspace_files`;
  - `TaskHandoff.model_validate_json(h.model_dump_json()) == h`, and the same for a `TaskReport` built around a valid `CoderResult`;
  - an extra field and a wrong `protocol_version` are both rejected;
  - `TaskReport` rejects the statuses `not_started` and `in_progress`;
  - `task_status_for` covers every row of the status table in [contracts/handoff-protocol.md](contracts/handoff-protocol.md#status-rule-spec-fr-010).
- [X] T028 [P] [US2] Add `test_report_for_wrong_task_stops_the_run` to `tests/unit/test_team_graph.py`. Call `_TeamNodes.record_report` directly with a state whose `current_handoff.task_id` is `T1` and whose `last_report.task_id` is `T2`, and assert it raises `LLMServiceError` whose message names both IDs.

### Implementation for User Story 2

- [X] T029 [US2] In `orchestration/team_graph.py` `_TeamNodes.record_report`, check `last_report.task_id == current_handoff.task_id` before storing anything. If they differ, raise `LLMServiceError("Task report for <got> does not match handoff <expected>")` ([contracts/handoff-protocol.md › Lifecycle](contracts/handoff-protocol.md#lifecycle) step 3).
- [X] T030 [US2] Run `pytest tests/unit/test_handoff_protocol.py tests/unit/test_team_graph.py`, and fix `orchestration/protocol.py` until T027 and T028 pass.

**Checkpoint**: Handoffs and reports are verified and can be inspected in every result.

---

## Phase 5: User Story 3 - Stop cleanly when a requirement can't be built or a task fails (Priority: P3)

**Goal**: An empty requirement raises an error. A non-software request is declined. A failed task
stops later handoffs, but the full result is still returned. A helper-only task with nothing to
run counts as completed.

**Independent Test**: The US3 tests in `test_team_graph.py` and `test_pm_agent.py`, plus
[quickstart.md](quickstart.md) step 6.

### Tests for User Story 3 ⚠️ (write first; they must fail)

- [X] T031 [P] [US3] Add to `tests/unit/test_pm_agent.py`: `specify` with a declined draft (`is_software_requirement=False`, `decline_reason="Not software"`) returns `decline_reason`, `specification=None` and `tasks=[]`; `SpecificationDraft` rejects a declined draft that has no reason; and a static check that `SPECIFY_PROMPT` contains the words "standard-library Python" so the decline rule for software the system can't build stays in the prompt (spec FR-012, US3 scenario 4).
- [X] T032 [P] [US3] Add to `tests/unit/test_team_graph.py`:
  - `run_dev_team("   ", dependencies=...)` raises `InvalidRequirementError`, makes no model call (the scripted model's `calls` is empty) and writes no files.
  - A declined run returns outcome `declined`, `tasks == []`, `code == []` and `execution_result.status == "not_run"`.
  - A 2-task run where T1's code fails on every run (script an `exec_python` of a `main.py` that raises, until the revision limit) ends with T1 `failed`, T2 `not_started` with no handoff, outcome `failed` with "T1" in the reason, and a final run that is recorded.
  - A 2-task run where T1 writes only `clock.py`, makes no `exec_python` call and finishes normally gives T1 status `completed` (spec US3 scenario 5).
  - A 1-task run whose only task writes `clock.py` and no `main.py` ends with `execution_result.status == "not_run"` and outcome `completed` (spec FR-016: no entry point means not run).
  - `run_dev_team(requirement, workspace=<folder containing a file>, dependencies=...)` raises `InvalidWorkspaceError` and makes no model call (spec FR-009).
  - A Coder model call that raises inside task T1 gives an `LLMServiceError` whose message starts with `"Task T1 failed:"` (spec edge case: name the stage).

### Implementation for User Story 3

- [X] T033 [US3] In `orchestration/team_graph.py` `run_dev_team`, raise `InvalidRequirementError("Requirement is empty. Describe the software you want built.")` when `requirement.strip()` is empty, before the workspace or dependencies are created.
- [X] T034 [US3] In `agents/pm_agent.py` `PMNodes.specify`, handle a declined draft: store only the `requirement` memory record, log `"PM: declined: %s"`, and return `specification=None`, `tasks=[]`, `decline_reason=draft.decline_reason` and `consolidation_attempts=0`.
- [X] T035 [US3] In `orchestration/team_graph.py`:
  - `route_after_planning`: return `"finalize"` when `decline_reason` is set.
  - `build_team_graph`: add `finalize` to the conditional edges from `specify`.
  - `route_after_record`: return `"final_run"` as soon as any task is `failed`, so later tasks stay `not_started` (spec FR-010a).
  - `finalize`: when `decline_reason` is set, build outcome `declined` with no tasks, no code and `ExecutionResult.not_run()`.
- [X] T036 [US3] Run `pytest tests/unit` and make T031 and T032 pass.

**Checkpoint**: All three user stories work and are tested.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, quality gates and end-to-end validation.

- [X] T037 [P] Update `README.md`:
  - Intro: the PM and Coder agents are built, and the QA agent is still a placeholder.
  - Repository layout: add `orchestration/` and `specs/002-pm-agent/`.
  - Add a "Run a requirement through the team" section with the `python -m orchestration.team_graph "<requirement>"` command and a `run_dev_team` Python example.
  - Add a "How the team works" section containing the **system diagram** from [plan.md › System Diagram](plan.md#system-diagram-to-be-added-to-readmemd) and a short explanation of the shared `TeamState` keys and the `current_handoff` protocol.
  - Add implementation-decision bullets for the single team graph with the Coder agent as a subgraph, the handoff protocol and its JSON serialization, consolidation above 8 tasks, and the final run.
  - Add `MAX_TASKS` and `MAX_CONSOLIDATION_ATTEMPTS` to the constants note under Configuration.
  - Add a "Cost" note: a typical run makes 1 PM call plus 3–5 Coder calls per task. There's no
    run-wide cap; the worst case is 99 model calls (1 specify + 2 consolidations + 8 tasks × 12
    Coder calls), as the spec's assumptions state.
  - Update "Run the tests" to say there are two smoke tests.
- [X] T038 [P] In `specs/002-pm-agent/checklists/requirements.md`, update the stale Notes: the result has five parts including `execution_result`, and the three defaults were settled by clarification and planning.
- [X] T039 Run `ruff check . && ruff format --check .` and fix every finding in the new and changed files.
- [X] T040 Run the full [quickstart.md](quickstart.md) validation, steps 1–7, including both smoke tests, a manual CLI run, the handoff inspection, the declined and empty-requirement paths, and the Coder-only path. Record the wall-clock time of the `test_smoke_team` run and confirm it's under 10 minutes (SC-003). Before release, also run the smoke requirement 10 times by hand and confirm at least 9 succeed (SC-002). Record any deviation.
  - **Validation record (2026-10-15)**: steps 1–7 passed. 130 unit tests passed; both smoke tests
    passed (`test_smoke_team` took 45.6 s, under the 10-minute SC-003 target); the manual CLI run
    completed in 47 s with outcome `completed`; the France and React requests were declined with
    reasons and no files; the empty requirement exited 1 with `InvalidRequirementError`; the
    Coder-only run succeeded. **Deviation**: the SC-002 check (10 runs by hand, at least 9 succeed)
    has not been run yet; it is a release step.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup. Blocks all user stories.
- **US1 (Phase 3)**: Depends on Foundational. This is the MVP.
- **US2 (Phase 4)**: Depends on US1, because it hardens and tests the handoff that US1 wires up.
- **US3 (Phase 5)**: Depends on US1, because it adds branches to US1's graph. Independent of US2,
  so it can run in parallel with Phase 4.
- **Polish (Phase 6)**: Depends on every story you want to ship.

### Task Dependencies (beyond phase order)

- T006 → T007 → T008 → T009 (same file, `orchestration/protocol.py`)
- T009 → T010, T013; T009 + T013 → T014; T010 + T011 → T012 → T015
- T005 has no dependencies within Phase 2. It must be done before T021 and T023, which use `invoke_model`
- T012 + T020 → T021; T010 → T022; T020 + T021 + T022 → T023 → T024 → T025 → T026
- T029 is after T023 (same file); T033–T035 are after T025 (same files)

### Within Each User Story

- Tests first, and they must fail. Then models and helpers, then nodes, then wiring, then the
  checkpoint run.

### Parallel Opportunities

- Phase 1: T002, T003 and T004 (different files).
- Phase 2: T005 at any time; T010, T011 and T013 once T009 is done; T014 once T013 is done.
- US1 tests: T016, T018 and T019 in parallel. T017 shares a file with T016, so do it after T016.
- US2 tests T027 and T028; US3 tests T031 and T032.
- Phases 4 and 5 can be worked on in parallel after US1, but T029 and T035 both edit
  `orchestration/team_graph.py`, so merge them carefully.
- Polish: T037 and T038.

---

## Parallel Example: User Story 1

```bash
# Write all US1 tests together (each must fail first):
Task: "T016/T017 PM node and consolidation tests in tests/unit/test_pm_agent.py"
Task: "T018 two-task team graph test in tests/unit/test_team_graph.py"
Task: "T019 team smoke test in tests/integration/test_smoke_team.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1: Setup → Phase 2: Foundational.
2. Phase 3: User Story 1, through T026 (both smoke tests pass).
3. **Stop and validate**: run quickstart steps 1–4.

### Incremental Delivery

1. Setup + Foundational → the foundation is ready.
2. US1 → the requirement → spec → tasks → code path works (MVP).
3. US2 → the handoff is verified and inspectable.
4. US3 → clean failure, decline and empty-input handling.
5. Polish → README diagram, lint, full quickstart.

---

## Notes

- [P] tasks = different files, no dependency on an unfinished task.
- Commit after each task or logical group. Every commit that touches agents, prompts, graph
  wiring or memory must keep both smoke tests passing (constitution Principle III).
- `TeamResult` is a new output schema and `CoderResult` is unchanged. Say so in the PR
  description (constitution Principle II).
