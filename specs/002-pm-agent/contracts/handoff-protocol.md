# Contract: PM → Coder Handoff Protocol (version 1)

How the PM side tells the Coder agent that a task is ready, and how the Coder agent reports back.
Both messages are Pydantic models in `orchestration/protocol.py`, kept in `TeamState`, and are
JSON-serializable. Field rules are in [data-model.md](../data-model.md#handoff-protocol).

## Lifecycle

1. `dispatch_task` picks the first task with status `not_started`. It builds its `TaskHandoff`
   with `build_handoff(...)`, sets the task to `in_progress`, stores the handoff on the task's
   `TaskRecord`, and writes it to `TeamState.current_handoff`.
2. **A non-empty `current_handoff` means a task is ready for the Coder agent.** The `coder` node
   runs only when it's set. It reads it, runs the Coder subgraph, and writes
   `TeamState.last_report`.
3. `record_report` checks that `last_report.task_id == current_handoff.task_id`. It stores the
   report on the `TaskRecord`, sets the status to `completed` or `failed`, refreshes
   `TeamState.code`, and clears `current_handoff` and `last_report` to `None`. This is the
   per-task progress written back to shared state.
4. Routing: the next `not_started` task goes back to step 1. A failed task, or no tasks left,
   goes to `final_run`.

Each handoff and report is validated when it's built. A message that fails validation stops the
run with `LLMServiceError` and is never passed on (spec FR-007).

## `TaskHandoff` example

```json
{
  "protocol_version": "1",
  "run_id": "3f9c2e7a1b8d4c60a5e1f2d3c4b5a697",
  "task_id": "T2",
  "title": "Print the Los Angeles time from main.py",
  "description": "Write main.py so it imports the helper from clock.py and prints its result.",
  "acceptance_criteria": [
    "Running `python main.py` prints one line with a date and an HH:MM time.",
    "Exit code is 0."
  ],
  "priority": "high",
  "depends_on": ["T1"],
  "context": {
    "name": "LA clock",
    "description": "A command-line tool that prints the current date and time in Los Angeles.",
    "out_of_scope": ["Other time zones."],
    "requirements": [
      {"id": "R2", "statement": "The tool MUST print the result to standard output when run."}
    ],
    "acceptance_criteria": [
      {"id": "AC2", "requirement_id": "R2", "text": "`python main.py` prints the date and time and exits 0."}
    ]
  },
  "workspace_files": ["clock.py"]
}
```

`context.requirements` holds only the requirements this task covers. Other requirements, such as
`R1`, which T1 covered, are left out.

## `TaskReport` example

```json
{
  "protocol_version": "1",
  "task_id": "T2",
  "status": "completed",
  "coder_result": {
    "code": [{"path": "clock.py", "content": "..."}, {"path": "main.py", "content": "..."}],
    "explanation": "main.py prints the current Los Angeles date and time using clock.py ...",
    "plan": {"steps": ["..."], "trace": [], "iterations": 2, "revision_attempts": 0, "stop_reason": "completed"},
    "execution_result": {"status": "succeeded", "success": true, "exit_code": 0, "stdout": "...", "stderr": "",
                         "truncated": false, "duration_seconds": 0.05, "entrypoint": "main.py"}
  }
}
```

`coder_result` is the Coder agent's `CoderResult`, unchanged
([001 data-model](../../001-coder-agent/data-model.md#coderresult)).

## Status rule (spec FR-010)

| `coder_result` | `status` |
|----------------|----------|
| `execution_result.success` is true | `completed` |
| `execution_result.status == "not_run"` and `plan.stop_reason == "completed"` | `completed` |
| Anything else: a failed or timed-out run, or `iteration_limit`, `revision_limit` or `rejected` | `failed` |

## Serialization guarantees

- `TaskHandoff.model_validate_json(handoff.model_dump_json()) == handoff`, and the same holds for
  `TaskReport`. A unit test checks this.
- Unknown fields are rejected (`extra="forbid"`).
- JSON Schemas come from `TaskHandoff.model_json_schema()` and `TaskReport.model_json_schema()`.
- Any change to a required field, or any rename, bumps `protocol_version` and is called out in
  the PR (constitution Principle II).
