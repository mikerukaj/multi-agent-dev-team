# Implementation Plan: Coder Agent

**Branch**: `001-coder-agent` | **Date**: 2026-10-09 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-coder-agent/spec.md`

## Summary

Build one Coder agent that takes a natural language coding task and returns a validated
`CoderResult` with four fields: `code`, `explanation`, `plan` and `execution_result`.

The agent is a LangGraph `StateGraph` with these nodes:

- `plan` makes the plan before any code is written (FR-002).
- `reason` and `act` form a ReAct loop (Thought → Action → Observation). The model's text is the
  Thought, its native tool calls are the Actions, and the tool results are the Observations.
  The loop is capped at 10 iterations, with at most 3 revisions after failed runs.
- `finalize` builds the result from the real workspace and the last real run, so file contents
  and run status cannot be misreported.

The agent has three custom tools:

- `read_file` and `write_file` are confined to the workspace.
- `exec_python` runs code with `subprocess` under a configurable timeout, with no stdin, a reduced
  environment, and the whole process group killed on timeout.

Memory has two layers. A sliding-window buffer keeps the last N turns, and a Chroma semantic
store is queried before **every** LLM call (`plan`, each `reason`, and `finalize`).

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: `langgraph` 1.x, `langchain-anthropic` 1.x, `langchain-core`,
`chromadb` 1.x (with its built-in ONNX embedding function), `pydantic` 2.x, `python-dotenv`.
Exact versions are pinned in `requirements.txt` at implementation time
([research R11](research.md#r11-dependencies-and-versions)).

**LLM**: Claude Sonnet 5.5, `claude-sonnet-5-5` (constitution Principle IV)

**Storage**:
- Chroma, embedded `PersistentClient` at `.chroma/`, or `HttpClient` when `CHROMA_HOST` is set.
- Generated code goes to the local file system under `workspace/<run_id>/`.

**Testing**: `pytest`, with unit tests using an injected fake chat model and one `smoke`-marked
integration test against the real model. Linting with `ruff`.

**Target Platform**: Linux (local dev and the repo's Docker image)

**Project Type**: Python library with a thin command-line entry point (`python -m agents.coder_agent`)

**Performance Goals**: The smoke task completes in < 2 min (SC-003); typical runs take 3–5 LLM
calls.

**Constraints**:
- At most 10 ReAct iterations and 3 revisions.
- Generated code runs with a 30 s timeout (configurable).
- Captured output is capped at 10 000 chars per stream.
- No writes outside the workspace (SC-005).
- Secrets are not passed to generated code.

**Scale/Scope**: One agent, one task per call, one developer at a time. No concurrency
requirements.

No open NEEDS CLARIFICATION items; all were resolved in [research.md](research.md).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | How the design complies | Pre-research | Post-design |
|-----------|------------------------|:---:|:---:|
| I. Clean Code | Small single-purpose modules (tools, memory, graph nodes, schemas); type hints and docstrings on public APIs; limits and prompts are named constants in `config.py` / `agents/prompts.py`; tool errors are explicit `ERROR:` observations; agent errors are typed exceptions; Ruff gate. | ✅ | ✅ |
| II. Structured Agent Outputs | `CoderResult` and its sub-models are Pydantic v2 with `extra="forbid"` and cross-field validators; validated before return; the `plan` node uses structured output ([data-model.md](data-model.md)). | ✅ | ✅ |
| III. Smoke Test Gate | `tests/integration/test_smoke_coder_agent.py` runs the compiled graph on the Los Angeles task, asserts the four fields are non-empty, and skips with a reason when there is no key ([contract](contracts/coder-agent-api.md#smoke-test-contract-principle-iii-spec-fr-012)). | ✅ | ✅ |
| IV. Mandated Stack | Orchestration in LangGraph only; LLM is `claude-sonnet-5-5`; all memory goes through Chroma. The embedder is Chroma's built-in function, which is part of Chroma and not a second LLM or store ([R5](research.md#r5-embeddings-for-chroma)). | ✅ | ✅ |
| V. Simplicity & Config | One `config.py` for the model ID, Chroma settings, limits and paths; secrets come from env; `.env.example` lists all variables; no speculative abstractions (no repeat-action detector, no summarizer). | ✅ | ✅ |

**Gate result**: PASS. No violations, so Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-coder-agent/
├── plan.md              # This file
├── research.md          # Phase 0: decisions R1–R12
├── data-model.md        # Phase 1: output models, graph state, memory records
├── quickstart.md        # Phase 1: validation guide
├── contracts/
│   ├── coder-agent-api.md   # run_coder_agent, errors, result JSON, smoke test contract
│   └── tools.md             # read_file, write_file, exec_python
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks — not created here)
```

### Source Code (repository root)

The repo already has `agents/`, `tools/`, `orchestration/` and `tests/`, so the plan uses those
and adds `memory/`.

```text
config.py                    # Single source of settings (model ID, limits, paths, Chroma)
pyproject.toml               # ruff + pytest config (pythonpath, "smoke" marker)
requirements.txt             # pinned dependencies
.env.example                 # ANTHROPIC_API_KEY, CHROMA_PATH, CHROMA_HOST, EXEC_TIMEOUT_SECONDS, ...

agents/
├── __init__.py
├── coder_agent.py           # run_coder_agent(), build_coder_graph(), nodes, routing, __main__ CLI
├── schemas.py               # CoderResult, GeneratedFile, ExecutionPlan, ReActStep, ExecutionResult, enums
├── state.py                 # CoderState
├── dependencies.py          # AgentDependencies (llm, memory, buffer, settings)
├── context.py               # build_llm_messages(): memory retrieval + window for every LLM call
├── prompts.py               # system / plan / explanation prompts
└── errors.py                # InvalidTaskError, AgentConfigurationError, LLMServiceError

tools/
├── __init__.py
├── workspace.py             # resolve_in_workspace() path confinement
├── file_tools.py            # read_file, write_file
└── exec_python.py           # exec_python (subprocess, timeout, process-group kill, truncation)

memory/
├── __init__.py
├── conversation_buffer.py   # ConversationBuffer (sliding window of N turns)
├── semantic_memory.py       # SemanticMemory over a Chroma collection (add, retrieve)
├── sqlite_compat.py         # Swaps in pysqlite3 when system sqlite3 < 3.35 (research R11a)
└── inspect.py               # python -m memory.inspect --last N

conftest.py                  # Root pytest config: loads the sqlite shim first

tests/
├── conftest.py              # tmp workspace, tmp Chroma, fake chat model fixtures
├── unit/
│   ├── test_file_tools.py
│   ├── test_exec_python.py
│   ├── test_conversation_buffer.py
│   ├── test_semantic_memory.py
│   ├── test_schemas.py
│   ├── test_workspace.py
│   ├── test_context.py
│   ├── test_graph_routing.py
│   ├── test_loop_limits.py
│   ├── test_task_rejection.py
│   └── test_memory_cli.py
└── integration/
    └── test_smoke_coder_agent.py   # marker: smoke

orchestration/               # untouched; reserved for future multi-agent wiring
```

**Structure Decision**: This is a single Python project using the existing top-level packages.
Agent-specific code goes in `agents/`, reusable tools in `tools/`, and both memory layers in
`memory/`, so the future PM and QA agents can reuse the tools and memory. `workspace/` and
`.chroma/` are git-ignored.

## Key Design Points

1. **Memory before every LLM call**: one helper, `build_prompt(state, node)`, calls
   `SemanticMemory.retrieve()` and `ConversationBuffer.window()` and assembles the prompt. All
   three LLM-calling nodes use it, so retrieval cannot be skipped
   ([R4](research.md#r4-two-layer-memory)).
2. **Writes to memory**: the task and plan after `plan`; each thought and observation after
   `act`; the result summary after `finalize`.
3. **Loop control**: the routing function after `act` checks `revision_attempts` first, then
   `iteration` ([R3](research.md#r3-loop-detection), [state transitions](data-model.md#state-transitions)).
4. **Honest finalize**: if files changed since the last run, `finalize` runs `main.py` itself
   ([R9](research.md#r9-building-the-structured-result)).
5. **Sandbox limits**: `exec_python` provides process isolation only. The Docker container is the
   outer boundary ([R7](research.md#r7-exec_python-sandboxing)).
6. **Dependency injection**: the model, memory, conversation buffer and settings travel together
   in one `AgentDependencies` object ([contract](contracts/coder-agent-api.md#agentdependencies)).
   This keeps every public function at 4 parameters or fewer (Principle I) and lets unit tests
   and the smoke test run with a fake model and a temporary memory.

## Spec Alignment Notes

- During planning I updated the spec's Assumptions: persistent memory between runs is now in
  scope (Chroma layer), and the 10-iteration cap is stated.
- The 3-revision limit (FR-009) and the 10-iteration cap work together. Whichever is reached
  first ends the loop.

## Complexity Tracking

No constitution violations to justify.
