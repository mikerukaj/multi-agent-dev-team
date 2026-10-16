# Quickstart: Validate the PM Agent and Handoff

Steps that prove the feature works end to end. Contracts:
[team-api.md](contracts/team-api.md) and [handoff-protocol.md](contracts/handoff-protocol.md).

## Prerequisites

The same as [001 quickstart](../001-coder-agent/quickstart.md#prerequisites): Python 3.12, the
`.venv` installed from `requirements.txt`, and `ANTHROPIC_API_KEY` in `.env` for the smoke tests
and manual runs.

## 1. Lint (quality gate)

```bash
ruff check . && ruff format --check .
```

Expected: no findings.

## 2. Unit tests (no API key needed)

```bash
pytest tests/unit -q
```

Expected: all pass, including the new tests:

| Test file | Proves |
|-----------|--------|
| `test_llm.py` | The shared `invoke_model` helper wraps model errors with the stage name and passes agent errors through. |
| `test_protocol_models.py` | Every task-list rule in spec FR-004 is rejected with a clear message: duplicate IDs, bad dependencies, unknown or uncovered requirements, empty lists, and bad ID formats. Nine tasks still validate, because consolidation handles the count. |
| `test_pm_agent.py` | After the PM `specify` node runs, state has a non-empty `tasks` list of valid `TaskRecord`s, all `not_started`, and a valid `specification`. Also: declined requirements, and consolidation of 9 tasks to at most 8, with `TaskPlanningError` once the attempt limit is reached. |
| `test_handoff_protocol.py` | A handoff holds only the covered requirements and has `priority`. `TaskHandoff` and `TaskReport` survive a JSON round trip. |
| `test_team_graph.py` | Two-task scripted run: tasks are handed off in order, each status is written back after its task, `code` grows, a failed task stops later handoffs, the final run is recorded, and the outcome is correct. |

## 3. Smoke tests (real model; this is the merge gate)

```bash
pytest -m smoke -v
```

Expected: `test_smoke_coder_agent` (unchanged) and `test_smoke_team` both pass. Without a key,
both are reported as **skipped** with the reason `ANTHROPIC_API_KEY not set`.

## 4. Manual run

```bash
python -m orchestration.team_graph "Build a command-line application that displays the current date and time in Los Angeles, California"
```

Expected:

- stderr shows progress lines, in order: the specification and its task count, then each task
  handed off and completed, then the final run.
- stdout is a `TeamResult` JSON with `outcome.status` set to `"completed"`, every task
  `completed` with a `handoff` and a `report`, and `execution_result.stdout` containing the Los
  Angeles date and time.
- A new folder under `workspace/` holds the files listed in `code`.

## 5. Handoff inspection

From the JSON in step 4, pick any task and check:

- `handoff.context.requirements` lists only the IDs in `task.covers`;
- `handoff.priority` is set;
- `report.task_id` equals `handoff.task_id`.

## 6. Declined and failure paths

```bash
python -m orchestration.team_graph "What is the capital of France?"
```

Expected: `outcome.status` is `"declined"` with a reason, `tasks` and `code` are empty, and no
workspace files are written.

```bash
python -m orchestration.team_graph "Build a React web app for my recipes"
```

Expected: `outcome.status` is `"declined"`, and the reason says only standard-library Python
programs can be built. No tasks run.

```bash
python -m orchestration.team_graph ""
```

Expected: exit code 1 and `InvalidRequirementError` on stderr.

## 7. Coder-only path unchanged

```bash
python -m agents.coder_agent "Write a script that prints the first 10 primes"
```

Expected: the same behavior as before this feature (spec FR-013, SC-007).
