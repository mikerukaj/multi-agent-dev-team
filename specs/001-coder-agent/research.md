# Research: Coder Agent

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-10-09

Each entry records a decision, why it was made, and what else was considered.

## R1. Graph shape: custom LangGraph `StateGraph` vs. prebuilt ReAct agent

- **Decision**: Build a custom `StateGraph` with explicit nodes:
  `plan → reason ⇄ act → finalize`.
- **Rationale**: The feature needs behavior the prebuilt agent does not give directly: memory
  retrieval before *every* LLM call (including planning and the final explanation), a hard
  10-iteration cap, a separate 3-revision cap on failed runs, a planning step before any code is
  written (FR-002), and a final step that builds the result from real workspace state. Explicit
  nodes keep each of these visible and testable, which Principle I asks for.
- **Alternatives considered**: LangGraph's prebuilt ReAct agent with pre-model hooks and
  `recursion_limit`. Rejected: the recursion limit raises an error instead of producing a
  graceful "iteration_limit" result, and the planning/finalize steps would still need custom
  nodes around it.

## R2. Thought → Action → Observation with native tool calling

- **Decision**: Use the model's native tool calling. In the `reason` node the model returns text
  (recorded as the **Thought**) plus zero or more tool calls (the **Action**). The `act` node runs
  the tools and appends their results (the **Observation**). No tool calls means the model is
  done.
- **Rationale**: Native tool calls give validated tool arguments, so there is no fragile parsing of
  "Action:" lines from free text. The system prompt requires a short thought before every action
  so the trace stays readable.
- **Alternatives considered**: Text-only ReAct with regex parsing of `Thought:/Action:` lines.
  Rejected as brittle and harder to validate.

## R3. Loop detection

- **Decision**: An `iteration` counter in graph state, incremented once per `reason` call. After
  each `act`, routing goes to `finalize` with `stop_reason = "iteration_limit"` when
  `iteration >= MAX_ITERATIONS` (10). A separate `revision_attempts` counter counts the
  `exec_python` runs made after the first failed run. Once it reaches `MAX_REVISIONS` (3), the
  loop ends: with `stop_reason = "revision_limit"` if the last run failed, or `"completed"` if it
  succeeded. This means the reported count is always the true number of revisions and never
  exceeds 3.
- **Rationale**: Matches the user's 10-iteration cap and spec FR-009 at the same time. Ending in
  `finalize` (not raising) means the developer always gets an honest structured result.
- **Alternatives considered**: Detecting repeated identical tool calls. Deferred (YAGNI); the
  counter alone meets the requirement.

## R4. Two-layer memory

- **Decision**:
  - **Layer 1 – sliding window**: a `ConversationBuffer` keeps the last `N` ReAct turns
    (default `N = 6`). A turn is one model message plus the tool results it caused, so tool
    calls are never separated from their results. The task and plan are always kept.
  - **Layer 2 – semantic store**: a Chroma collection `coder_agent_memory`. Every observation,
    thought and final result is written with metadata (`run_id`, `kind`, `iteration`,
    `created_at`). Before every LLM call (`plan`, each `reason`, and `finalize`) the agent
    queries the top `k = 4` records using the task plus the latest observation as the query,
    drops records past a distance threshold, and puts the rest in a "Relevant past context"
    block in the prompt.
- **Rationale**: The window bounds prompt size within a run; Chroma brings back context that
  fell out of the window and context from earlier runs.
- **Alternatives considered**: Summarizing old turns with the LLM. Rejected: it adds an extra
  LLM call per turn and the semantic store already covers recall.

## R5. Embeddings for Chroma

- **Decision**: Use Chroma's built-in default embedding function (a small local
  sentence-embedding model run through ONNX).
- **Rationale**: Anthropic does not offer an embeddings API, and Principle IV fixes Sonnet 5.5 as the
  *LLM*, not the embedder. Chroma's built-in function keeps memory fully inside Chroma
  (Principle IV: "All persistent agent memory and retrieval MUST go through Chroma") with no extra
  vendor or key.
- **Alternatives considered**: A third-party embeddings API (adds a vendor and a secret);
  `sentence-transformers` (pulls in PyTorch, a much larger image).
- **Note**: The embedding model is downloaded on first use (about 80 MB). The Docker image should
  pre-fetch it at build time so the first run is not slow.

## R6. Chroma deployment mode

- **Decision**: Embedded `PersistentClient` at `CHROMA_PATH` (default `.chroma/`) by default.
  If `CHROMA_HOST` is set, use an `HttpClient` to a Chroma server instead (for
  `docker-compose`). The choice is made in one place in `config.py`.
- **Rationale**: Zero setup for local development and tests; a server option for containers.
- **Alternatives considered**: Server-only. Rejected: every developer and test run would need
  a running Chroma container.

## R7. `exec_python` sandboxing

- **Decision**: Run `sys.executable -E -s <path>` with `subprocess.Popen`, where:
  - `-E -s` ignore `PYTHON*` variables and user site-packages. (`-I` was the first choice, but it
    also removes the script's folder from `sys.path`, so `main.py` could not import its own
    helper modules. Changed during implementation; covered by a unit test.)
  - `cwd` is the task workspace and `<path>` must resolve inside it;
  - `stdin` is `DEVNULL`, so code waiting for input gets end-of-file instead of hanging;
  - `timeout` comes from config (`EXEC_TIMEOUT_SECONDS`, default 30);
  - the child runs in a new session, and on timeout the whole process group is killed;
  - the environment is reduced to `PATH`, `HOME`, `LANG` and `TZ`, so `ANTHROPIC_API_KEY` and
    other secrets are not passed to generated code;
  - stdout and stderr are each truncated to `MAX_OUTPUT_CHARS` (default 10 000), with a
    `truncated` flag set.
- **Rationale**: Covers the spec edge cases (timeouts, input waits, large output) and keeps
  secrets away from generated code.
- **Limitation**: This is *process* isolation, not a security boundary. Generated code can still
  reach the network and read files the user can read. The container (Dockerfile) is the outer
  sandbox; stronger isolation (gVisor, a seccomp profile, a separate container per run) is out of
  scope for this feature.
- **Alternatives considered**: Running generated code in Docker per run. Rejected for v1: slow and
  needs Docker-in-Docker.

## R8. `read_file` / `write_file` path confinement

- **Decision**: Both tools take a path relative to the workspace, resolve it with
  `Path.resolve()`, and refuse anything not inside the resolved workspace (this blocks `..` and
  symlink escapes). A refusal comes back as a tool error observation, so the model sees it and the
  trace records it.
- **Rationale**: Meets FR-004 and SC-005.

## R9. Building the structured result

- **Decision**: `finalize` builds `CoderResult` mostly from facts, not from the model:
  - `code` ← the files actually in the workspace (read from disk);
  - `execution_result` ← the last real `exec_python` result. If files changed after the last run,
    or nothing was ever run, `finalize` runs the entry file (`main.py`) once more itself;
  - `plan` ← the plan steps and the recorded ReAct trace;
  - `explanation` ← the only part written by the model, through one structured-output call
    (with memory retrieval first, per R4).

  The full object is then validated with Pydantic before it is returned.
- **Rationale**: Guarantees that file contents match disk (spec US1 scenario 2) and that run
  status is honest (FR-010), so the model cannot claim a success that didn't happen.
- **Alternatives considered**: Having the model produce the whole result as structured output.
  Rejected: the model could misreport code or run status.

## R10. Rejecting non-coding tasks

- **Decision**: Empty or whitespace-only tasks raise `InvalidTaskError` before the graph starts
  (no files, no LLM call). The `plan` node's structured output includes `is_coding_task` and
  `rejection_reason`; when the task is not a coding task, routing goes straight to `finalize`
  with `stop_reason = "rejected"` and `execution_result.status = "not_run"`.
- **Rationale**: Covers spec US3 at the lowest cost: one LLM call, no tools.

## R11. Dependencies and versions

- **Decision**: Python 3.12 (matches the dev machine). Add to `requirements.txt`, pinned to exact
  versions at implementation time: `langgraph` (1.x), `langchain-anthropic` (1.x), `langchain-core`,
  `chromadb` (1.x), `pydantic` (2.x), `python-dotenv`, `pytest`, `ruff`.
- **Note**: The dev environment currently has `pydantic 1.9.2`; the project needs Pydantic 2,
  so set up a fresh virtual environment from `requirements.txt`.
- **Model**: `claude-sonnet-5-5`, defined once as `CODER_MODEL` in `config.py`, with
  `max_tokens` set from `llm_max_tokens` (default 8192) so `write_file` calls carrying a whole
  file are not cut off, and `max_retries` from `llm_max_retries` (default 2).

## R11a. SQLite on older Linux hosts

- **Decision**: Add `pysqlite3-binary` (Linux x86_64 only) and `memory/sqlite_compat.py`, which
  swaps it in as `sqlite3` only when the system SQLite is older than 3.35. The `memory` package
  imports it first, so any import of `memory.*` makes Chroma loadable.
- **Rationale**: Chroma requires SQLite 3.35 or later; the RHEL 8 dev machine has 3.26.
  The Docker image (Debian) already has a new enough SQLite, so the shim does nothing there.
- **Alternatives considered**: Building SQLite from source (heavy); Chroma server mode only
  (the client package still checks SQLite on import).

## R12. Testing strategy

- **Decision**:
  - **Unit tests** for the tools (path escape, timeout, input waits, truncation), the
    conversation buffer (window size, tool-call pairing), and graph routing (iteration cap,
    revision cap, rejection) using an injected fake chat model.
  - **Smoke test** (`tests/integration/test_smoke_coder_agent.py`, marker `smoke`): calls
    `run_coder_agent` with the Los Angeles date/time task against the real model, using a
    temporary workspace and a temporary Chroma directory (passed in through
    `AgentDependencies`). It asserts all four fields validate and are non-empty, that the run
    succeeded, and that the output contains a date and a time. It is skipped with a reason when
    `ANTHROPIC_API_KEY` is not set (Principle III).
  - The spec's "9 of 10 runs" target (SC-002) is checked by hand before release, not by an
    automated test.
- **Rationale**: Fast, free unit tests cover the control logic; the single paid smoke test proves
  the full path end to end.
