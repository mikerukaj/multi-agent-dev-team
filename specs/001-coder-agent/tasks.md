---

description: "Task list for the Coder Agent feature"
---

# Tasks: Coder Agent

**Input**: Design documents from `/specs/001-coder-agent/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Included. The spec requires a smoke test (FR-012), the constitution makes it a merge
gate (Principle III), and the plan defines unit tests with an injected fake chat model.

**Organization**: Tasks are grouped by user story so each story can be built and tested on its own.

**Document status**: The plan documents were updated on 2026-10-09 after `/speckit-analyze`, so
they now match the clarified spec (FR-003, FR-004, FR-005a, FR-012, FR-012a) and these tasks. If
anything still differs, follow the **spec**.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on unfinished tasks)
- **[Story]**: The user story the task belongs to (US1, US2, US3)

## Path Conventions

Single Python project at the repo root, using the existing `agents/`, `tools/` and `tests/`
packages plus a new `memory/` package ([plan.md › Project Structure](plan.md#project-structure)).
All settings live in `config.py` (constitution Principle V).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project skeleton, dependencies and tooling.

- [X] T001 Create packages and test folders: empty `agents/__init__.py`, `tools/__init__.py`, `memory/__init__.py`, and folders `tests/unit/` and `tests/integration/` (each with an empty `__init__.py`); leave the existing `orchestration/` untouched
- [X] T002 Fill `requirements.txt` with exact pinned versions of `langgraph` (1.x), `langchain-anthropic` (1.x), `langchain-core`, `chromadb` (1.x), `pydantic` (2.x), `python-dotenv`, `pytest`, `ruff`; choose the newest release of each that is at least two weeks old, then create `.venv` with Python 3.12 and confirm `pip install -r requirements.txt` succeeds
- [X] T003 [P] Create `pyproject.toml` with `[tool.ruff]` (line-length 100, target py312, lint rules `E,F,I,B,UP,SIM,N`) and `[tool.pytest.ini_options]` (`pythonpath = ["."]`, `testpaths = ["tests"]`, marker `smoke: calls the real Anthropic API`)
- [X] T004 [P] Create root `.gitignore` covering `.venv/`, `.env`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `workspace/`, `.chroma/`
- [X] T005 [P] Fill `.env.example` with every env-overridable setting from T006 and no real values, each with a one-line comment: `ANTHROPIC_API_KEY=`, `WORKSPACE_ROOT=workspace`, `CHROMA_PATH=.chroma`, `CHROMA_HOST=`, `CHROMA_PORT=8000`, `EXEC_TIMEOUT_SECONDS=30`, `MAX_OUTPUT_CHARS=10000`, `MAX_OBSERVATION_CHARS=4000`, `MEMORY_WINDOW_TURNS=6`, `MEMORY_TOP_K=4`, `MEMORY_MAX_DISTANCE=1.2`, `LLM_MAX_TOKENS=8192`, `LLM_MAX_RETRIES=2`, `LOG_LEVEL=INFO`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Config, schemas, errors, workspace safety and both memory layers. Every LLM call in
every story depends on these.

**⚠️ CRITICAL**: No user story work can start until this phase is done.

- [X] T006 Create `config.py`: a frozen `Settings` dataclass and a `load_settings()` that calls `dotenv.load_dotenv()` and reads env overrides. Constants: `CODER_MODEL = "claude-sonnet-5-5"`, `MAX_ITERATIONS = 10`, `MAX_REVISIONS = 3`, `ENTRYPOINT = "main.py"`, `MEMORY_COLLECTION = "coder_agent_memory"`. Env-overridable: `exec_timeout_seconds` (30), `max_output_chars` (10000), `max_observation_chars` (4000), `memory_window_turns` (6), `memory_top_k` (4), `memory_max_distance` (1.2), `workspace_root` (`workspace`), `chroma_path` (`.chroma`), `chroma_host` (None), `chroma_port` (8000), `llm_max_tokens` (8192), `llm_max_retries` (2), `log_level` (`INFO`). An env variable set to an empty string (for example `CHROMA_HOST=`) counts as unset and uses the default. Docstrings on every field
- [X] T007 [P] Create `agents/errors.py` with base `CoderAgentError` and subclasses `InvalidTaskError`, `InvalidWorkspaceError`, `AgentConfigurationError`, `LLMServiceError`, each with a docstring saying when it is raised ([contracts/coder-agent-api.md](contracts/coder-agent-api.md#run_coder_agent))
- [X] T008 [P] Create `agents/schemas.py` with Pydantic v2 models (all `extra="forbid"`) exactly as in [data-model.md](data-model.md):
  - enums `ExecutionStatus` and `StopReason`;
  - `GeneratedFile` (validator: relative path, no `..`, not absolute);
  - `ReActStep`;
  - `ExecutionResult` (validator: `success == (status == "succeeded")`; `exit_code` is None when `timed_out` or `not_run`), plus a `not_run()` classmethod;
  - `ExecutionPlan` (`steps` min length 1; bounds on `iterations` and `revision_attempts` taken from `config`);
  - `CoderResult` (`explanation` non-blank; cross-field rule for `rejected`);
  - `PlanDecision` (`steps: list[str]` with `min_length=1`, `is_coding_task: bool`, `rejection_reason: str | None`, with a validator requiring a non-blank `rejection_reason` when `is_coding_task` is false), used as the structured output of the plan LLM call;
  - `ExplanationDraft` (`explanation: str`), used as the structured output of the finalize LLM call
- [X] T009 [P] Create `tools/workspace.py`:
  - `resolve_in_workspace(workspace: Path, relative_path: str) -> Path` resolves symlinks and raises `ValueError` if the result is not inside `workspace.resolve()`;
  - `prepare_workspace(path: Path | None, root: Path, run_id: str) -> Path` creates `root/run_id` when `path` is None. When `path` is given, it MUST be missing or an empty directory, otherwise it raises `InvalidWorkspaceError` (spec FR-003). It returns the resolved path;
  - `list_workspace_files(workspace: Path) -> list[GeneratedFile]` returns all files sorted by path, skipping `__pycache__/`
- [X] T010 Create `agents/state.py` with `CoderState` as a `TypedDict` holding the fields in [data-model.md › CoderState](data-model.md#coderstate-langgraph-graph-state) (depends on T008)
- [X] T011 Create `tests/conftest.py` with these fixtures (depends on T006, T014, T015, T019):
  - `settings` (a `Settings` with `tmp_path` workspace root and Chroma path, and a short timeout);
  - `workspace` (an empty `tmp_path` subfolder);
  - `fake_embedding` (a deterministic hash-based Chroma embedding function, so no model download is needed);
  - `memory` (a `SemanticMemory` on a temporary Chroma using `fake_embedding`);
  - `ScriptedChatModel`, a `BaseChatModel` subclass that returns queued `AIMessage`s (with optional `tool_calls`) from `_generate`, returns itself from `bind_tools`, returns queued Pydantic objects from `with_structured_output(...).invoke`, and records every prompt it receives;
  - `retrieve_spy`, which wraps `memory.retrieve` and counts calls;
  - `make_dependencies(script)`, a factory returning `AgentDependencies(llm=ScriptedChatModel(script), memory=<spied memory>, buffer=ConversationBuffer(settings.memory_window_turns), settings=settings)`
- [X] T012 [P] Write `tests/unit/test_schemas.py`: valid `CoderResult` round-trips through `model_dump(mode="json")`; rejects an extra top-level field, a blank explanation, `success=True` with `status="failed"`, a `GeneratedFile` path with `..`, `iterations=11`, `revision_attempts=4`, and `stop_reason="rejected"` with non-empty `code`
- [X] T013 [P] Write `tests/unit/test_workspace.py`: `resolve_in_workspace` accepts `pkg/a.py` and rejects `../x`, `/etc/passwd`, and a symlink pointing outside; `prepare_workspace` creates `root/run_id`, accepts a missing or empty path, and raises `InvalidWorkspaceError` for a folder containing a file; `list_workspace_files` skips `__pycache__`
- [X] T014 [P] Create `memory/conversation_buffer.py` with a `ConversationBuffer(max_turns)` class whose `window(messages: list[BaseMessage]) -> list[BaseMessage]` returns the last `max_turns` turns. A turn is one `AIMessage` plus the `ToolMessage`s answering its `tool_calls`; turns are never split ([research R4](research.md#r4-two-layer-memory))
- [X] T015 [P] Create `memory/semantic_memory.py`:
  - a `MemoryRecord` dataclass (`kind`, `text`, `run_id`, `iteration`, plus `created_at` defaulting to now in UTC);
  - a `SemanticMemory` class with:
    - `from_settings(settings, embedding_function=None)`, which picks `HttpClient` when `chroma_host` is set and `PersistentClient(chroma_path)` otherwise, uses Chroma's default embedding function when none is given, and wraps connection errors in `AgentConfigurationError` naming the setting to fix;
    - `add(records)`, which stores records with ids `"{run_id}:{iteration}:{kind}:{n}"`;
    - `retrieve(query, top_k, max_distance) -> list[str]`, which returns documents within the distance threshold, nearest first;
    - `recent(limit) -> list[MemoryRecord]`;
    - `wipe()`, which deletes and recreates the collection
- [X] T016 [P] Write `tests/unit/test_conversation_buffer.py`: window keeps exactly the last N turns; never returns a `ToolMessage` without its `AIMessage`; handles an AI message with two tool calls as one turn; returns everything when there are fewer than N turns
- [X] T017 [P] Write `tests/unit/test_semantic_memory.py` using the `memory` fixture: `add` then `retrieve` returns the matching record first; `max_distance` filters far records; `recent` orders newest first; `wipe` empties the collection; data written by one `SemanticMemory` is visible to a second one on the same path (persistence between runs)
- [X] T018 Create `agents/prompts.py` with named string constants:
  - `SYSTEM_PROMPT`: role; workspace-only file access; write a one or two sentence thought before every tool call; entry file is `main.py`; standard library only; run the code with `exec_python` before finishing; stop calling tools when done;
  - `PLAN_PROMPT`: produce ordered steps and decide `is_coding_task`;
  - `EXPLANATION_PROMPT`: explain what the code does and how to run it, given files and run output;
  - `PAST_CONTEXT_TEMPLATE`: a "Relevant past context" block
- [X] T019 Create `agents/dependencies.py` and `agents/context.py` (depends on T010, T014, T015, T018):
  - `agents/dependencies.py` holds a frozen dataclass `AgentDependencies(llm, memory, buffer, settings)` and its `from_settings(settings)` classmethod. That method builds `ChatAnthropic(model=CODER_MODEL, max_tokens=settings.llm_max_tokens, max_retries=settings.llm_max_retries)`, raising `AgentConfigurationError("ANTHROPIC_API_KEY is not set ...")` if the key is missing, then builds `SemanticMemory.from_settings(settings)` and `ConversationBuffer(settings.memory_window_turns)` ([contract](contracts/coder-agent-api.md#agentdependencies)). Grouping these keeps every public function at 4 parameters or fewer (constitution Principle I);
  - `agents/context.py` holds `build_llm_messages(state, instruction, dependencies) -> list[BaseMessage]`. In order, it MUST:
    1. build a query from `state["task"]` and the latest observation;
    2. call `dependencies.memory.retrieve(...)`;
    3. log the retrieved items at DEBUG;
    4. return the system prompt, the past-context block (only if anything was retrieved), the task and plan steps, `instruction`, and `dependencies.buffer.window(state["messages"])`.

  This is the single path every LLM call uses, so memory is retrieved before every call
- [X] T020 Write `tests/unit/test_context.py` using `make_dependencies`: `retrieve_spy` counts exactly one call per `build_llm_messages` call; `AgentDependencies.from_settings` raises `AgentConfigurationError` when `ANTHROPIC_API_KEY` is unset (monkeypatched); past context appears in the prompt when found and is absent when nothing matches; only the last N turns of `messages` are included; task and plan steps are always present

**Checkpoint**: Foundation ready. `pytest tests/unit` passes and `ruff check .` is clean.

---

## Phase 3: User Story 1 - Turn a coding task into working, explained code (Priority: P1) 🎯 MVP

**Goal**: Given the Los Angeles date/time task, the agent plans, writes `main.py` in a new
workspace, runs it, and returns a validated `CoderResult` with all four fields filled in.

**Independent Test**: `pytest -m smoke` passes with a real API key. Separately,
`tests/unit/test_graph_routing.py` passes with the scripted fake model.

### Tests for User Story 1 ⚠️

> Write these first and confirm they fail before implementing.

- [X] T021 [P] [US1] Write `tests/unit/test_file_tools.py` per [contracts/tools.md](contracts/tools.md):
  - `write_file` creates parent folders and returns `Wrote <n> characters to <path>`;
  - `read_file` returns contents, and truncates with a note past `max_observation_chars`;
  - both return `ERROR: ...` (never raise) for `../escape.py`, absolute paths, a symlink inside the workspace pointing outside it, and a missing file;
  - after the refused writes, no file outside the workspace was created or changed (spec SC-005)
- [X] T022 [P] [US1] Write `tests/unit/test_exec_python.py` with tiny scripts written into the `workspace` fixture:
  - success gives `succeeded` with exit code 0 and stdout captured;
  - `raise SystemExit(3)` gives `failed` with exit code 3;
  - `input()` gives a quick `failed` result with `EOFError` in stderr, not a hang;
  - `time.sleep(10)` with a 1 s timeout gives `timed_out` with `exit_code=None`, and a child process it started is also killed;
  - printing 20 000 chars gives `truncated=True` with output capped;
  - with `ANTHROPIC_API_KEY` set in the parent, the script sees it as unset (FR-005a);
  - a path outside the workspace returns `ERROR:`
- [X] T023 [P] [US1] Write the happy-path test in `tests/unit/test_graph_routing.py` by calling `run_coder_agent(task, workspace=workspace, dependencies=make_dependencies(script))`. Script the fake model with:
  1. a `PlanDecision` with 3 steps;
  2. an AI message calling `write_file(main.py, print("hi"))`;
  3. an AI message calling `exec_python(main.py)`;
  4. a final AI message with no tool calls;
  5. an `ExplanationDraft`.

  Assert: `stop_reason == "completed"`; `iterations == 3`; `code == [GeneratedFile("main.py", 'print("hi")')]` and it matches disk; `execution_result.success` with stdout `hi\n`; the trace has thought, action and observation per round and ends with one closing step (`action=None`); `retrieve_spy` counted exactly 5 calls, one before **each** of the fake model's 5 calls; memory now holds `task`, `plan`, `thought`, `observation` and `result` records
- [X] T024 [P] [US1] Write `tests/integration/test_smoke_coder_agent.py` with `@pytest.mark.smoke`. It MUST:
  - skip with reason `"ANTHROPIC_API_KEY not set"` when the key is missing;
  - use the `settings` and `workspace` fixtures, so the test has its own Chroma folder and never touches the developer's memory (FR-012a);
  - call `run_coder_agent("Write a python application that displays the current date and time in Los Angeles, California", workspace=workspace, dependencies=AgentDependencies.from_settings(settings))`. Passing `dependencies` explicitly is what keeps the test on the temporary Chroma folder; without it the default `.chroma/` would be used;
  - assert the result is a `CoderResult`; `code` has ≥ 1 file with non-empty content; `explanation.strip()` is non-empty; `plan.steps` has ≥ 1 item; `execution_result` is present;
  - also assert `execution_result.success is True` and that `stdout` matches both a date (`\d{4}-\d{2}-\d{2}` or a month name) and a time (`\d{1,2}:\d{2}`) (spec FR-012 as clarified)

### Implementation for User Story 1

- [X] T025 [P] [US1] Create `tools/file_tools.py` with `make_file_tools(workspace, settings) -> list[BaseTool]`, which returns LangChain `@tool` functions `read_file(path)` and `write_file(path, content)`. Use `resolve_in_workspace`, return `ERROR: <reason>` strings instead of raising, and truncate `read_file` output to `max_observation_chars` (makes T021 pass)
- [X] T026 [P] [US1] Create `tools/exec_python.py` with:
  - `run_python_file(workspace, relative_path, timeout_seconds, max_output_chars) -> ExecutionResult`, which:
    - runs `subprocess.Popen([sys.executable, "-I", path], cwd=workspace, stdin=DEVNULL, start_new_session=True, env={PATH, HOME, LANG, TZ only})`;
    - on `TimeoutExpired`, calls `os.killpg(proc.pid, SIGKILL)` and collects the output;
    - truncates each stream and measures duration;
  - `format_execution_observation(result) -> str` in the text format from [contracts/tools.md](contracts/tools.md#exec_python);
  - `make_exec_python_tool(workspace, settings)`, a LangChain tool `exec_python(path)` that returns the formatted text and attaches the `ExecutionResult` as the tool's artifact (`response_format="content_and_artifact"`).

  This makes T022 pass
- [X] T027 [US1] In `agents/coder_agent.py`, implement `plan_node(state)`. It calls the LLM with `with_structured_output(PlanDecision)` using `build_llm_messages(..., PLAN_PROMPT, ...)`, stores `plan_steps`, `is_coding_task` and `rejection_reason`, and writes `task` and `plan` records to memory
- [X] T028 [US1] In `agents/coder_agent.py`, implement `reason_node(state)`. It increments `iteration`, calls the tool-bound LLM with `build_llm_messages`, appends the `AIMessage` to `messages`, and writes a `thought` record to memory using the message text
- [X] T029 [US1] In `agents/coder_agent.py`, implement `act_node(state)`. For each tool call on the last `AIMessage` it:
  - runs the matching tool and appends a `ToolMessage`;
  - appends one `ReActStep` (for `write_file`, replace `content` with `"<n chars>"` in `action_input`);
  - stores `last_execution` from the `exec_python` artifact;
  - writes an `observation` record to memory
- [X] T030 [US1] In `agents/coder_agent.py`, implement `finalize_node(state)`. It:
  - collects `code` via `list_workspace_files`;
  - uses `last_execution` (or `ExecutionResult.not_run()` if none);
  - adds a final `ReActStep` with `action=None` for the closing thought, only when `stop_reason == "completed"` and the last `AIMessage` had no tool calls;
  - calls the LLM with `with_structured_output(ExplanationDraft)` via `build_llm_messages(..., EXPLANATION_PROMPT, ...)`;
  - builds and validates a `CoderResult`;
  - writes a `result` record to memory
- [X] T031 [US1] In `agents/coder_agent.py`, implement `build_coder_graph(dependencies, workspace)`; nodes reach the model, memory, buffer and settings through `dependencies`. It wires `START → plan → reason`, adds a `route_after_reason` conditional (tool calls go to `act`, otherwise to `finalize` with `stop_reason="completed"`), adds `act → reason`, and `finalize → END`, then returns the compiled graph (makes T023 pass)
- [X] T032 [US1] In `agents/coder_agent.py`, implement `run_coder_agent(task, workspace=None, *, dependencies=None) -> CoderResult` as in the [contract](contracts/coder-agent-api.md#run_coder_agent). It:
  - makes a `run_id` (uuid4);
  - takes `settings` from `dependencies.settings`, or from `load_settings()` when `dependencies` is None;
  - calls `prepare_workspace(workspace, settings.workspace_root, run_id)`, which raises `InvalidWorkspaceError` for a non-empty folder, before building any default dependencies (so a bad workspace never needs an API key or Chroma);
  - then, if `dependencies` is None, builds `AgentDependencies.from_settings(settings)`;
  - invokes the graph with `recursion_limit = 2 * MAX_ITERATIONS + 5`;
  - wraps Anthropic API errors (raised after the client's `llm_max_retries` retries) and structured-output parse failures in `LLMServiceError`;
  - returns the validated result
- [X] T033 [US1] In `agents/coder_agent.py`, add a `main()` and an `if __name__ == "__main__":` CLI. It takes the task as the first argument and an optional `--workspace PATH`, configures logging from `settings.log_level`, prints `result.model_dump_json(indent=2)` to stdout, and exits 1 with the error message on stderr for any `CoderAgentError`
- [ ] T034 [US1] Run `pytest tests/unit` and `pytest -m smoke -v` (with a key in `.env`) and fix failures until both pass; record the smoke test's wall-clock time against SC-003 (< 2 min) in the PR description

**Checkpoint**: The MVP works end to end. The smoke test gate (constitution Principle III) passes.

---

## Phase 4: User Story 2 - Report honestly when the code does not work (Priority: P2)

**Goal**: Failed and timed-out runs are reported as failed. The loop stops after 10 iterations
(`iteration_limit`), or after 3 revisions following the first failed run (`revision_limit` if the
last run failed, `completed` if it succeeded), whichever comes first. The result never claims success for code that wasn't run after its last
change.

**Independent Test**: `pytest tests/unit/test_loop_limits.py` passes with the scripted fake model.
Quickstart step 6 (sleep 120 s) returns `timed_out` within the timeout.

### Tests for User Story 2 ⚠️

- [X] T035 [P] [US2] Write `tests/unit/test_loop_limits.py` using `make_dependencies` and these cases:
  - **iteration limit**: the model calls `read_file` on every round, so the graph stops with `stop_reason="iteration_limit"`, `iterations == 10`, the fake model called exactly 10 times in `reason`, and no closing `action=None` step in the trace;
  - **revision limit**: every `exec_python` hits a script that exits 1, so it stops after 4 runs with `stop_reason="revision_limit"`, `revision_attempts == 3` and `execution_result.success is False`;
  - **recovery**: the first run fails and the second succeeds, so `revision_attempts == 1`, `stop_reason="completed"` and `success`;
  - **gave up without revising**: the first run fails and the model stops without running again, so `revision_attempts == 0`;
  - **keeps running after recovery**: run 1 fails and the model then makes three more runs that all succeed (editing between them), so the loop stops right after the fourth run with `revision_attempts == 3` and `stop_reason="completed"`, and `revision_attempts` never exceeds 3;
  - **stale run**: the model writes a file after its last `exec_python` and then stops, so finalize re-runs `main.py` and reports that run;
  - **never run**: the model writes `main.py` and stops without running it, so finalize runs it;
  - **timeout**: the script sleeps past the timeout, so `status="timed_out"` and `success is False`

### Implementation for User Story 2

- [X] T036 [US2] In `act_node` in `agents/coder_agent.py`, set `files_changed_since_run = True` after a successful `write_file`. After `exec_python`, clear it; then, if `first_failure_seen` is already set, increment `revision_attempts`; then set `first_failure_seen` when the status is `failed` or `timed_out` ([data-model.md](data-model.md#coderstate-langgraph-graph-state))
- [X] T037 [US2] In `agents/coder_agent.py`, add `route_after_act(state)` and wire it in place of the plain `act → reason` edge. It first checks `revision_attempts >= MAX_REVISIONS` (sets `stop_reason="revision_limit"` if the last run failed, or `"completed"` if it succeeded, and goes to `finalize`), then `iteration >= MAX_ITERATIONS` (sets `stop_reason="iteration_limit"` and goes to `finalize`), and otherwise goes to `reason`
- [X] T038 [US2] In `finalize_node` in `agents/coder_agent.py`, if `last_execution is None` or `files_changed_since_run` is set, and `ENTRYPOINT` exists in the workspace, call `run_python_file` on it and use that result. This extra run does not change `revision_attempts`. Copy `revision_attempts` from state into `ExecutionPlan` (makes T035 pass)
- [X] T039 [US2] In `agents/prompts.py` and `reason_node`, add a per-round status line to the instruction: `"Iteration {i} of {MAX_ITERATIONS}. Revisions used: {r} of {MAX_REVISIONS}."`. Add guidance to `SYSTEM_PROMPT`: after a failed run, read the error, fix the code and run it again

**Checkpoint**: US1 and US2 both pass. Failures are reported honestly and loops always end.

---

## Phase 5: User Story 3 - Reject tasks the agent cannot act on (Priority: P3)

**Goal**: An empty task raises `InvalidTaskError` before any work. A non-coding request returns a
`rejected` result with no files and a `not_run` execution result.

**Independent Test**: `pytest tests/unit/test_task_rejection.py` passes.

### Tests for User Story 3 ⚠️

- [X] T040 [P] [US3] Write `tests/unit/test_task_rejection.py` using `make_dependencies`:
  - `""` and `"   \n"` raise `InvalidTaskError`, with the fake model never called and no workspace folder created;
  - a `PlanDecision(is_coding_task=False, rejection_reason="Not a coding request", steps=["Rejected: not a coding request"])` gives `stop_reason="rejected"`, `code == []`, `execution_result.status == "not_run"` and an explanation containing the reason;
  - no `reason` or `act` calls happen;
  - a `PlanDecision` with `is_coding_task=False` and no `rejection_reason`, or with `steps=[]`, fails validation and surfaces as `LLMServiceError`

### Implementation for User Story 3

- [X] T041 [US3] In `run_coder_agent` in `agents/coder_agent.py`, raise `InvalidTaskError("Task is empty ...")` when `task.strip()` is empty, before `prepare_workspace` or any model or memory setup
- [X] T042 [US3] In `agents/coder_agent.py`, add `route_after_plan(state)`: when `is_coding_task` is false, set `stop_reason="rejected"` and go to `finalize`; otherwise go to `reason`. In `finalize_node`, when rejected, skip the explanation LLM call, use `rejection_reason` as the explanation, and return an empty `code` list and `ExecutionResult.not_run()` (makes T040 pass)
- [X] T043 [US3] In `PLAN_PROMPT` in `agents/prompts.py`, define what counts as a coding task (a request to write or change a program or script) and require a short `rejection_reason` otherwise

**Checkpoint**: All three user stories work and are covered by tests.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: The memory wipe command (FR-012a), packaging, documentation and final checks.

- [X] T044 [P] Create `memory/inspect.py` as a CLI run with `python -m memory.inspect`. It supports `--last N` (prints the N most recent records: `created_at`, `run_id`, `kind`, first 120 chars) and `--wipe` (asks for confirmation unless `--yes` is passed, calls `SemanticMemory.wipe()`, and prints how many records were removed) (spec FR-012a)
- [X] T045 [P] Write `tests/unit/test_memory_cli.py`: `--last 2` prints two records newest first; `--wipe --yes` empties the temporary store; `--wipe` without confirmation leaves it unchanged
- [X] T046 [P] Write `Dockerfile`: start from `python:3.12-slim`; install the `tzdata` OS package (needed by `zoneinfo` for the Los Angeles task); `pip install -r requirements.txt`; pre-download Chroma's default embedding model at build time ([research R5](research.md#r5-embeddings-for-chroma)); copy the source; default `CMD ["pytest", "-m", "smoke", "-v"]`
- [X] T047 [P] Write `docker-compose.yml` with an `agent` service (built from `Dockerfile`, `env_file: .env`, `workspace/` mounted, `CHROMA_HOST=chroma`) and a `chroma` service (official `chromadb/chroma` image pinned to the same version as `requirements.txt`, with a named volume for persistence)
- [X] T048 [P] Write `README.md` covering what the Coder agent does, setup (venv and `.env`), running a task with `python -m agents.coder_agent`, the result fields (link `specs/001-coder-agent/data-model.md`), running tests and the smoke test, wiping memory with `python -m memory.inspect --wipe`, and the sandbox limits (process isolation only; the container is the boundary)
- [x] T049 [P] Bring the plan documents up to date with the 2026-10-09 clarifications and analysis fixes in `specs/001-coder-agent/research.md`, `specs/001-coder-agent/contracts/coder-agent-api.md`, `specs/001-coder-agent/contracts/tools.md`, `specs/001-coder-agent/data-model.md`, `specs/001-coder-agent/plan.md` and `specs/001-coder-agent/quickstart.md` (done during `/speckit-analyze` remediation, before implementation)
- [X] T050 Run `ruff check . --fix` and `ruff format .` over the repo and resolve every remaining warning (constitution Principle I, quality gate 1)
- [ ] T051 Run every step in `specs/001-coder-agent/quickstart.md` (lint, unit tests, smoke test, manual run, memory check and wipe, workspace check, timeout path) and confirm each expected outcome. Before release, also run the smoke task 10 times by hand and confirm at least 9 succeed (spec SC-002)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: depends on Setup. Blocks all user stories.
- **US1 (Phase 3)**: depends on Foundational.
- **US2 (Phase 4)** and **US3 (Phase 5)**: depend on US1, because they extend the nodes and routing in `agents/coder_agent.py` that US1 creates. Their tests (T035, T040) can be written as soon as Phase 2 is done.
- **Polish (Phase 6)**: T044–T048 depend only on Phase 2 and can start early. T049 is already done. T050 and T051 run last.

### Key Task Dependencies

- T010 ← T008 · T019 ← T010, T014, T015, T018 · T011 ← T006, T014, T015, T019 · T020 ← T011, T019
- T012 ← T008 · T013 ← T009 · T016 ← T014 · T017 ← T015, T011
- T027 → T028 → T029 → T030 → T031 → T032 → T033 → T034 (same file, run in order)
- T025, T026 ← T009 · T029 ← T025, T026
- T036 → T037 → T038 (same file) · T039 ← T028
- T041 → T042 (same file) · T043 ← T018

### Within Each User Story

- Tests are written first and fail, then the implementation makes them pass.
- Tools before nodes, nodes before graph wiring, graph before the public entry point.

### Parallel Opportunities

- Phase 1: T003, T004 and T005 together after T001 and T002.
- Phase 2: T007, T008, T009, T014 and T015 together; then T012, T013 and T016 together; T017 and T020 after T011.
- US1: tests T021–T024 together; then T025 and T026 together.
- US2 and US3 tests (T035 and T040) can be written together.
- Polish: T044–T048 together.

---

## Parallel Example: User Story 1

```bash
# Write all US1 tests together:
Task: "Write tests/unit/test_file_tools.py (T021)"
Task: "Write tests/unit/test_exec_python.py (T022)"
Task: "Write happy-path test in tests/unit/test_graph_routing.py (T023)"
Task: "Write tests/integration/test_smoke_coder_agent.py (T024)"

# Then build both tools together:
Task: "Create tools/file_tools.py (T025)"
Task: "Create tools/exec_python.py (T026)"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1: Setup.
2. Phase 2: Foundational. This is critical because memory retrieval before every LLM call lives here.
3. Phase 3: US1.
4. **Stop and validate**: run `pytest tests/unit` and `pytest -m smoke`. The constitution's merge gate is now met.

### Incremental Delivery

1. Setup + Foundational gives you tested config, schemas, workspace safety and memory.
2. Add US1 for the working agent and passing smoke test (MVP).
3. Add US2 for loop limits and honest failure reporting.
4. Add US3 for task rejection.
5. Polish adds the memory wipe command, Docker, README and the plan document fixes.

---

## Notes

- [P] tasks touch different files and do not depend on unfinished tasks.
- Every change touching agents, prompts, graph wiring or memory MUST keep `pytest -m smoke` green before merge (constitution Principle III).
- Commit after each task or logical group, and stop at any checkpoint to validate.
