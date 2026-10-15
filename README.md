# Multi-Agent Dev Team

A team of AI agents for software tasks. The planned team is a PM agent, a Coder agent and a QA
agent. **Only the Coder agent is built so far.** `agents/pm_agent.py`, `agents/qa_agent.py` and
`orchestration/` are empty placeholders for later features.

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
agents/          Coder agent: graph and CLI (coder_agent.py), schemas, prompts, prompt builder
tools/           Agent tools: read_file / write_file, exec_python, workspace path checks
memory/          Sliding-window buffer, Chroma semantic memory, inspect/wipe command
config.py        Every setting in one place; overridable from the environment or .env
tests/unit/      Fast offline tests using a scripted fake model
tests/integration/  Smoke test against the real model
specs/001-coder-agent/  Spec, plan, research, data model, contracts and tasks for this feature
.specify/        Spec Kit config, templates and the project constitution
```

The project follows the Spec Kit workflow: constitution → spec → plan → tasks → implementation.
For why something is built the way it is, start with
[specs/001-coder-agent/spec.md](specs/001-coder-agent/spec.md) and
[research.md](specs/001-coder-agent/research.md).

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

### Run the tests

```bash
ruff check . && ruff format --check .   # lint gate
pytest tests/unit                        # offline, no API key needed
pytest -m smoke -v                       # real model; skipped if ANTHROPIC_API_KEY is not set
```

The smoke test sends the Los Angeles date/time task to the real agent. It checks that all four
result fields are filled in, that the run succeeded, and that the program printed a date and a
time. It is the merge gate: no change to agents, prompts, graph wiring or memory may merge while
it fails.

### Manage memory

```bash
python -m memory.inspect --last 10      # show recent memory records
python -m memory.inspect --wipe         # delete all long-term memory (asks to confirm)
```

Long-term memory is kept until you wipe it. Tests always use a temporary store.

### Docker

```bash
docker compose run --rm agent                                               # smoke test
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

## Implementation decisions

The full reasoning is in [research.md](specs/001-coder-agent/research.md).

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

The full list is in [.env.example](.env.example). The 10-round and 3-revision limits are fixed
constants in `config.py`.
