# Contract: Coder Agent Python API

The public entry point other code (tests, future PM/QA agents) depends on.

## `run_coder_agent`

```python
# agents/coder_agent.py
def run_coder_agent(
    task: str,
    workspace: Path | None = None,
    *,
    dependencies: AgentDependencies | None = None,
) -> CoderResult: ...
```

| Parameter | Meaning |
|-----------|---------|
| `task` | Natural language coding task. |
| `workspace` | Directory the agent may read, write and run in. It MUST be missing or empty (spec FR-003). Default: a new `WORKSPACE_ROOT/<run_id>/`. |
| `dependencies` | Test override for the model, memory, conversation buffer and settings, all together. Default: `AgentDependencies.from_settings(load_settings())`. |

### `AgentDependencies`

```python
# agents/dependencies.py
@dataclass(frozen=True)
class AgentDependencies:
    llm: BaseChatModel  # default: ChatAnthropic(model=CODER_MODEL, max_tokens=llm_max_tokens, max_retries=llm_max_retries)
    memory: SemanticMemory  # default: SemanticMemory.from_settings(settings)
    buffer: ConversationBuffer  # default: ConversationBuffer(settings.memory_window_turns)
    settings: Settings

    @classmethod
    def from_settings(cls, settings: Settings) -> "AgentDependencies": ...
```

Grouping these four into one object keeps every public function at 4 parameters or fewer
(constitution Principle I).

**Returns** a validated `CoderResult` ([data-model.md](../data-model.md#coderresult)).

**Raises**

| Error | When |
|-------|------|
| `InvalidTaskError` | `task` is empty or whitespace only. No files written, no LLM call. |
| `InvalidWorkspaceError` | `workspace` exists and is not empty. No files written, no LLM call. |
| `AgentConfigurationError` | `ANTHROPIC_API_KEY` missing when building default dependencies, or Chroma cannot be opened. Message says which setting to fix. |
| `LLMServiceError` | The model call still fails after `llm_max_retries` retries (default 2), or its structured answer cannot be parsed. |

Run failures of the *generated* code are **not** raised; they are reported in
`execution_result` (spec FR-010).

## `build_coder_graph`

```python
def build_coder_graph(dependencies: AgentDependencies, workspace: Path) -> CompiledStateGraph: ...
```

Returns the compiled LangGraph graph. Used by `run_coder_agent` and by routing unit tests.

## Result JSON shape

`CoderResult.model_dump(mode="json")` for the smoke task looks like:

```json
{
  "code": [
    {"path": "main.py", "content": "from datetime import datetime\n..."}
  ],
  "explanation": "main.py prints the current date and time in Los Angeles ...",
  "plan": {
    "steps": ["Use zoneinfo for America/Los_Angeles", "Write main.py", "Run and check output"],
    "trace": [
      {
        "iteration": 1,
        "thought": "I'll write main.py using zoneinfo.",
        "action": "write_file",
        "action_input": {"path": "main.py", "content": "<312 chars>"},
        "observation": "Wrote 312 characters to main.py"
      },
      {
        "iteration": 2,
        "thought": "Now run it.",
        "action": "exec_python",
        "action_input": {"path": "main.py"},
        "observation": "exit_code=0\nstdout:\nLos Angeles: 2026-10-09 08:15:02 PDT\n"
      },
      {"iteration": 3, "thought": "Output is correct. Done.", "action": null, "action_input": {}, "observation": null}
    ],
    "iterations": 3,
    "revision_attempts": 0,
    "stop_reason": "completed"
  },
  "execution_result": {
    "status": "succeeded",
    "success": true,
    "exit_code": 0,
    "stdout": "Los Angeles: 2026-10-09 08:15:02 PDT\n",
    "stderr": "",
    "truncated": false,
    "duration_seconds": 0.04,
    "entrypoint": "main.py"
  }
}
```

## Smoke test contract (Principle III, spec FR-012)

The smoke test MUST:

1. Call `run_coder_agent("Write a python application that displays the current date and time in Los Angeles, California", workspace=<tmp>, dependencies=AgentDependencies.from_settings(<test settings>))`. The test settings point `chroma_path` at a temporary folder, so the developer's memory is never read or written (spec FR-012a).
2. Assert the result is a `CoderResult` and that `code`, `explanation`, `plan` and
   `execution_result` are each present and non-empty (`code` has ≥ 1 file, `plan.steps` has
   ≥ 1 item, `explanation.strip()` is non-empty).
3. Assert `execution_result.success is True` and that `stdout` contains a date and a time
   (spec FR-012).
4. Be skipped with reason `"ANTHROPIC_API_KEY not set"` when the key is missing.
