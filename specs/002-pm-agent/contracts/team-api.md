# Contract: Dev Team Python API and CLI

The public entry point for the two-agent system. The Coder-only API in
[001 coder-agent-api.md](../../001-coder-agent/contracts/coder-agent-api.md) is unchanged (spec
FR-013).

## `run_dev_team`

```python
# orchestration/team_graph.py
def run_dev_team(
    requirement: str,
    workspace: Path | None = None,
    *,
    dependencies: AgentDependencies | None = None,
) -> TeamResult: ...
```

| Parameter | Meaning |
|-----------|---------|
| `requirement` | High-level software requirement in natural language. |
| `workspace` | Folder shared by every task. It MUST be missing or empty (spec FR-009). Default: a new `WORKSPACE_ROOT/<run_id>/`. |
| `dependencies` | The same `AgentDependencies` the Coder agent uses (model, memory, buffer, settings); both agents share it. Default: `AgentDependencies.from_settings(load_settings())`. |

**Returns** a validated `TeamResult` ([data-model.md](../data-model.md#teamresult)).

**Raises** (all subclass `CoderAgentError`)

| Error | When |
|-------|------|
| `InvalidRequirementError` | `requirement` is empty or whitespace only. No files written, no model call. |
| `InvalidWorkspaceError` | `workspace` exists and isn't empty. No files written, no model call. |
| `AgentConfigurationError` | API key missing or Chroma can't be opened (unchanged from 001). |
| `TaskPlanningError` | The task list still has more than `MAX_TASKS` tasks after `MAX_CONSOLIDATION_ATTEMPTS` consolidations (spec FR-004a). Nothing handed off. |
| `LLMServiceError` | A model call failed or returned an answer that fails validation. The message starts with `PM specify failed:`, `PM consolidate failed:` or `Task <id> failed:`. |

A declined requirement is **not** an error: it returns a `TeamResult` with outcome `declined`. A
task whose generated code fails is **not** an error either: it returns outcome `failed`.

## `build_team_graph`

```python
def build_team_graph(dependencies: AgentDependencies, workspace: Path) -> CompiledStateGraph: ...
```

Returns the compiled team graph over `TeamState`. Its nodes are `specify`, `consolidate`,
`dispatch_task`, `coder`, `record_report`, `final_run` and `finalize`. The `coder` node runs the
graph from `build_coder_graph(dependencies, workspace)`, compiled once per team graph. Used by
`run_dev_team` and by unit tests.

## PM node entry point (for tests)

```python
# agents/pm_agent.py
class PMNodes:
    def __init__(self, dependencies: AgentDependencies) -> None: ...
    def specify(self, state: TeamState) -> TeamState: ...  # partial update (TeamState is total=False)
    def consolidate(self, state: TeamState) -> TeamState: ...  # partial update (TeamState is total=False)
```

`specify` returns the state update that writes `specification`, `tasks` (every `TaskRecord` set to
`not_started`), `decline_reason` and `consolidation_attempts = 0`. This is the boundary that the
"after the PM node runs, shared state has a non-empty task list with the correct schema" unit test
checks.

## CLI

```bash
python -m orchestration.team_graph "<requirement>" [--workspace PATH]
```

- stdout: `TeamResult` as indented JSON.
- stderr: one progress line per step, through `logging` at `LOG_LEVEL` (default `INFO`).
- Exit code 0 when a result is returned, whatever its outcome. Exit code 1 on any
  `CoderAgentError`, with `<ErrorName>: <message>` on stderr.

## Result JSON shape (abridged)

```json
{
  "specification": {
    "name": "LA clock",
    "description": "A command-line tool that prints the current date and time in Los Angeles.",
    "requirements": [{"id": "R1", "statement": "The tool MUST print the current Los Angeles date and time."}],
    "acceptance_criteria": [{"id": "AC1", "requirement_id": "R1", "text": "Output contains a date and a HH:MM time."}],
    "assumptions": ["Python standard library only."],
    "out_of_scope": ["Other time zones."],
    "tasks": [{"id": "T1", "title": "Write main.py", "description": "...", "acceptance_criteria": ["..."],
               "priority": "high", "covers": ["R1"], "depends_on": []}]
  },
  "tasks": [
    {"task": {"id": "T1", "...": "..."}, "status": "completed",
     "handoff": {"protocol_version": "1", "task_id": "T1", "...": "..."},
     "report": {"protocol_version": "1", "task_id": "T1", "status": "completed", "coder_result": {"...": "..."}}}
  ],
  "code": [{"path": "main.py", "content": "..."}],
  "execution_result": {"status": "succeeded", "success": true, "exit_code": 0, "stdout": "2026-10-15 09:41:07 PDT\n", "...": "..."},
  "outcome": {"status": "completed", "reason": "All 1 tasks completed and the final run succeeded."}
}
```

## Smoke test contract (constitution Principle III, spec FR-014)

`tests/integration/test_smoke_team.py`, marked `smoke`:

- Skipped with the reason `ANTHROPIC_API_KEY not set` when there's no key.
- Calls `run_dev_team("Build a command-line application that displays the current date and time
  in Los Angeles, California", workspace=<tmp>, dependencies=<tmp Chroma>)`.
- Asserts:
  - the result is a `TeamResult`;
  - `specification` is not `None` and has at least one requirement and one task;
  - every task is `completed` and has a `handoff` and a `report`;
  - `code` is non-empty;
  - `outcome.status == "completed"`;
  - `execution_result.success` is true;
  - stdout matches the same date and time patterns as the Coder-only smoke test.
