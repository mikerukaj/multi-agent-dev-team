# Multi-Agent Dev Team

A team of AI agents for software tasks. The planned team is a PM agent, a Coder agent and a QA
agent. **The PM and Coder agents are built**; `agents/qa_agent.py` is still an empty placeholder.

- The **PM agent** takes a high-level requirement, writes a formal technical specification,
  breaks it into ordered tasks, and hands each task to the Coder agent through a structured,
  JSON-serializable protocol. Both agents run in one LangGraph graph and share one state. See
  [How the team works](#how-the-team-works).
- The **Coder agent** can also be used on its own, as described below.

The **Coder agent** takes a coding task in plain English, plans an approach, writes Python code
into its own workspace folder, runs it, and returns one validated, structured result:

| Field | Contents |
|-------|----------|
| `code` | Every file in the task's workspace, with its path and contents |
| `explanation` | What the code does and how to run it |
| `plan` | The planned steps, a step-by-step trace, rounds and revisions used, and why it stopped |
| `execution_result` | Whether the last run succeeded, its exit code, stdout and stderr |

The stack is fixed by the [project constitution](.specify/memory/constitution.md): **LangGraph**
for orchestration, **Claude Sonnet 5.5** (`claude-sonnet-5-5`) as the only LLM, and **Chroma** for
memory.

## Repository layout

```text
agents/          Coder agent (coder_agent.py), PM agent (pm_agent.py), schemas, prompts,
                 prompt builder (context.py), shared model-call helper (llm.py)
orchestration/   Team graph and CLI (team_graph.py), shared TeamState, handoff protocol models
tools/           Agent tools: read_file / write_file, exec_python, workspace path checks
memory/          Sliding-window buffer, Chroma semantic memory, inspect/wipe command
config.py        Every setting in one place; overridable from the environment or .env
tests/unit/      Fast offline tests using a scripted fake model
tests/integration/  Smoke tests against the real model (Coder alone, and the team)
specs/001-coder-agent/  Spec, plan, research, data model, contracts and tasks for the Coder agent
specs/002-pm-agent/     The same for the PM agent and the PM → Coder handoff
.specify/        Spec Kit config, templates and the project constitution
```

The project follows the Spec Kit workflow: constitution → spec → plan → tasks → implementation.
For why something is built the way it is, start with each feature's `spec.md` and
`research.md`: [001 Coder agent](specs/001-coder-agent/research.md) and
[002 PM agent](specs/002-pm-agent/research.md).

## Setup

Requirements: Python 3.12, and an Anthropic API key with access to `claude-sonnet-5-5`.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then set ANTHROPIC_API_KEY in .env
```

- The first real run downloads Chroma's embedding model (about 80 MB).
- Every setting in [.env.example](.env.example) is optional except `ANTHROPIC_API_KEY`.
- On hosts whose system SQLite is older than 3.35 (for example RHEL 8), the
  `pysqlite3-binary` package from `requirements.txt` is used automatically so Chroma can load.

### Run a task

```bash
python -m agents.coder_agent "Write a python application that displays the current date and time in Los Angeles, California"
```

The JSON result is printed to stdout. Each task gets a new folder under `workspace/`. To choose
the folder yourself, pass `--workspace PATH`; it must be missing or empty.

From Python:

```python
from agents.coder_agent import run_coder_agent

result = run_coder_agent("Write a script that prints the first 10 primes")
print(result.execution_result.stdout)
```

### Run a requirement through the team

```bash
python -m orchestration.team_graph "Build a command-line application that displays the current date and time in Los Angeles, California"
```

Progress lines go to stderr and the JSON `TeamResult` goes to stdout. It has five parts:
`specification`, `tasks` (each with its status, handoff and report), `code`, `execution_result`
(one final run of `main.py`) and `outcome` (`completed`, `failed` or `declined`, with a reason).
Every task in a requirement shares one new workspace folder under `workspace/`.

From Python:

```python
from orchestration.team_graph import run_dev_team

result = run_dev_team("Build a CLI that converts Celsius to Fahrenheit")
print(result.outcome.status, result.execution_result.stdout)
```

A request that isn't standard-library Python software (for example "Build a React web app") is
declined with a reason, and no code is written.

### Run the tests

```bash
ruff check . && ruff format --check .   # lint gate
pytest tests/unit                        # offline, no API key needed
pytest -m smoke -v                       # real model; skipped if ANTHROPIC_API_KEY is not set
```

There are two smoke tests, and together they are the merge gate: no change to agents, prompts,
graph wiring or memory may merge while either fails.

- `test_smoke_coder_agent` sends the Los Angeles date/time task to the Coder agent alone. It
  checks that all four result fields are filled in, that the run succeeded, and that the program
  printed a date and a time.
- `test_smoke_team` sends the same request as a requirement to the PM agent. It checks the
  specification, that every task completed with a handoff and a report, the code, a `completed`
  outcome, and a final run that printed a date and a time.

### Manage memory

```bash
python -m memory.inspect --last 10      # show recent memory records
python -m memory.inspect --wipe         # delete all long-term memory (asks to confirm)
```

Long-term memory is kept until you wipe it. Tests always use a temporary store.

### Docker

```bash
docker compose run --rm agent                                               # smoke tests
docker compose run --rm agent python -m agents.coder_agent "Write hello world"
```

Compose runs Chroma as its own service and keeps generated code in `./workspace`. `.env` is
optional; without it the smoke test is reported as skipped.

## How the Coder agent works

```text
plan ──► reason ⇄ act ──► finalize
  │                          ▲
  └── not a coding task ─────┘
```

1. **plan**: one structured model call decides whether the request is a coding task and lists
   the steps. Non-coding requests skip straight to finalize and return a "rejected" result.
2. **reason ⇄ act** (the ReAct loop): in each round the model writes a short Thought and calls
   tools (the Action), and the tool results come back as the Observation. The tools are:
   - `read_file` and `write_file`, which only work inside the workspace;
   - `exec_python`, which runs a file with a timeout (30 s by default).

   The loop ends when the model stops calling tools, after 10 rounds, or once 3 revisions have
   been made after the first failed run.
3. **finalize**: reads the files actually on disk, takes the last real run, and asks the model
   for a plain-language explanation. The result is validated before it is returned.

## How the team works

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

1. **specify** (PM): one structured model call turns the requirement into a
   `TechnicalSpecification`: name, description, requirements, acceptance criteria, assumptions,
   out-of-scope items and an ordered task list. It writes the spec and one `TaskRecord` per task
   (status `not_started`) into the shared `TeamState`. Requests it can't build are declined.
2. **consolidate** (PM): if there are more than 8 tasks, the PM merges them, at most twice.
   If there are still too many, the run stops with `TaskPlanningError` before any handoff.
3. **dispatch_task**: writes the next task's `TaskHandoff` to `current_handoff`. A set
   `current_handoff` is the signal that a task is ready. The handoff holds the task ID, title,
   description, acceptance criteria, priority and dependencies, only the parts of the spec the
   task covers, and the files already in the workspace.
4. **coder**: runs the unchanged Coder agent graph as a subgraph on the handoff and returns a
   `TaskReport` with the Coder agent's full result.
5. **record_report**: writes the report and the task's status (`completed` or `failed`) back to
   shared state, refreshes `code`, and clears `current_handoff`. A failed task stops all later
   handoffs.
6. **final_run** runs `main.py` once, with no model call, and **finalize** builds the validated
   `TeamResult`.

The handoff and report are versioned Pydantic models (`protocol_version: "1"`) that serialize with
`model_dump_json()`. Their JSON examples are in
[contracts/handoff-protocol.md](specs/002-pm-agent/contracts/handoff-protocol.md).

## Implementation decisions

The full reasoning is in the Coder agent's [research.md](specs/001-coder-agent/research.md) and
the PM agent's [research.md](specs/002-pm-agent/research.md).

- **Custom LangGraph graph, not the prebuilt ReAct agent.** Explicit nodes make it easy to plan
  before coding, search memory before every model call, and end on a limit with a normal result
  instead of an error.
- **Native tool calling for ReAct.** The model's text is the Thought and its tool calls are the
  Actions, so arguments arrive validated instead of being parsed out of free text.
- **Claude Sonnet 5.5 rather than Opus 5.5, for cost.** Sonnet 5.5 costs half as much ($2 / $10
  per million input / output tokens, against $4 / $20 for Opus 5.5). The choice isn't about tool
  calling: both models reject forced tool choice, which the next point works around.
- **Native structured output for the plan and explanation calls.** Both calls use
  `with_structured_output(..., method="json_schema")`, which sends the schema as the API's
  `output_config.format`, so the response is constrained to match it. LangChain's default
  (`method="function_calling"`) gets JSON back by forcing a tool call (`tool_choice` of type
  `tool`), and Claude Sonnet 5.5 rejects forced tool choice with a 400. `langchain-anthropic`
  only avoids forcing for the models it knows about (Opus 5.5 and Fable 5.1 in 1.7.4), so the
  plan call failed on Sonnet 5.5 until we set the method explicitly.
- **One graph for both agents.** The PM nodes and the handoff loop are nodes of one LangGraph
  graph, and the Coder agent's existing compiled graph runs inside its `coder` node as a
  subgraph. There are no separate processes, and the Coder agent's own state stays private.
- **A state key as the handoff protocol.** `current_handoff` holds a validated, versioned
  `TaskHandoff`, and `last_report` holds the `TaskReport`. Each handoff carries only the
  requirements the task covers, which keeps the tokens sent on every Coder round down.
- **Consolidation instead of truncation.** A task list over 8 is merged by the PM, not cut, so no
  requirement is dropped. The task count is deliberately not a schema rule, so an over-long list
  reaches the merge step instead of failing to parse.
- **One shared workspace per requirement.** Later tasks see and build on earlier tasks' files.
- **A final run with no model call.** After the last task (or a failed one), `main.py` runs once
  more, so the result proves the finished program works, not just the last task.
- **One helper for model errors.** `agents/llm.py:invoke_model` is the only place a model failure
  becomes `LLMServiceError`, named by stage (for example `PM specify failed:` or
  `Task T2 failed:`).
- **Two-layer memory.**
  - A sliding window keeps the last 6 turns. A turn is one model message plus its tool results,
    and turns are never split.
  - Chroma stores tasks, plans, thoughts, observations and results.

  One function, `build_llm_messages` in [agents/context.py](agents/context.py), builds every
  prompt and always searches Chroma first, so the "retrieve before every LLM call" rule can't be
  skipped.
- **Chroma's built-in embedding model.** Anthropic has no embeddings API, and using Chroma's own
  model keeps all memory inside Chroma, as the constitution requires, with no extra vendor or key.
- **The result is built from facts, not from the model.**
  - `code` is read from disk.
  - `execution_result` is the last real run. If the code changed after that run, or was never
    run, finalize runs `main.py` itself.
  - Only `explanation` is written by the model.

  This stops the agent from reporting code or a success that didn't happen.
- **Two limits.** Each round is counted, up to 10. Separately, `revision_attempts` counts runs
  after the first failed run, up to 3. It never counts a revision that didn't happen.
- **Process isolation only.** `exec_python` runs code in its own process group with:
  - no keyboard input;
  - only `PATH`, `HOME`, `LANG` and `TZ` in its environment, so the API key isn't passed on;
  - a timeout that kills the whole process tree;
  - stdout and stderr capped in size.

  It uses `python -E -s` rather than `-I`, because `-I` would stop `main.py` from importing its
  own helper files. This is **not** a security sandbox: generated code can still use the network
  and read or write any file your user can. The Docker container, which runs as a non-root user,
  is the real boundary.
- **One new, empty workspace per task.** Working on existing code is out of scope. A folder that
  already has files is rejected before any model call.
- **Dependencies grouped in one object.** `AgentDependencies` holds the model, memory, buffer and
  settings. This keeps every public function at 4 parameters or fewer (constitution Principle I)
  and lets tests swap in a scripted fake model and a temporary Chroma store.
- **The explanation call leaves out the tool-call history.** The Anthropic API rejects tool-call
  history when no tools are attached, so the files and run result are passed in directly instead.
- **Offline unit tests, one paid smoke test.** Unit tests use a scripted fake chat model and a
  hash-based fake embedder, so they need no network or key. Only the smoke test calls the real
  model.
- **Pinned dependencies.** Every package is pinned to a release at least two weeks old.

## Configuration

All settings live in [config.py](config.py). The values most often changed are:

| Variable | Default | Meaning |
|----------|---------|---------|
| `ANTHROPIC_API_KEY` | (none) | Required for real runs |
| `WORKSPACE_ROOT` | `workspace` | Parent folder for task workspaces |
| `CHROMA_PATH` / `CHROMA_HOST` | `.chroma` / unset | Embedded store, or a Chroma server if the host is set |
| `EXEC_TIMEOUT_SECONDS` | `30` | Time limit for each run of generated code |
| `MEMORY_WINDOW_TURNS` | `6` | Turns kept in the sliding window |
| `LOG_LEVEL` | `INFO` | `DEBUG` also logs the past context retrieved for each call |

The full list is in [.env.example](.env.example). These limits are fixed constants in
`config.py`: 10 rounds and 3 revisions per Coder task (`MAX_ITERATIONS`, `MAX_REVISIONS`), at most 8
tasks per requirement (`MAX_TASKS`), and at most 2 consolidations (`MAX_CONSOLIDATION_ATTEMPTS`).

### Cost

A typical team run makes 1 PM model call plus 3–5 Coder calls per task; the smoke requirement
takes about a minute. There is no run-wide cap on model calls. The limits above bound the worst
case at **99 model calls per requirement**: 1 specify call, up to 2 consolidation calls, and up to
12 Coder calls (1 plan, 10 rounds, 1 explanation) for each of up to 8 tasks. The final run makes
no model call.
