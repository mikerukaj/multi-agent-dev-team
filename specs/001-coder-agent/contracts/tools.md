# Contract: Agent Tools

Tools the model can call in the `act` step. Each is a LangChain tool bound to the task workspace.
Errors are returned to the model as observation text starting with `ERROR:`; tools never raise
into the graph.

## `read_file`

| Argument | Type | Rules |
|----------|------|-------|
| `path` | `str` | Relative to the workspace; must resolve inside it. |

**Returns**: file contents (truncated to `MAX_OBSERVATION_CHARS` with a note), or
`ERROR: <reason>` for a missing file, a path outside the workspace, or a non-UTF-8 file.

## `write_file`

| Argument | Type | Rules |
|----------|------|-------|
| `path` | `str` | Relative to the workspace; must resolve inside it. Parent folders are created. |
| `content` | `str` | Full file contents (overwrites). |

**Returns**: `Wrote <n> characters to <path>`, or `ERROR: <reason>`.
**Side effect** (applied by the `act` node): sets `files_changed_since_run = True`.

## `exec_python`

| Argument | Type | Rules |
|----------|------|-------|
| `path` | `str` | Workspace-relative `.py` file; must resolve inside it. |

**Behavior**: `sys.executable -E -s <path>` (not `-I`, which drops the script's folder from
`sys.path` and breaks multi-file programs), `cwd` = workspace, `stdin` = `DEVNULL`, reduced
environment (`PATH`, `HOME`, `LANG`, `TZ`), new session, timeout `EXEC_TIMEOUT_SECONDS`
(default 30, configurable). On timeout the process group is killed.

**Returns**: text summary for the model:

```text
status=<succeeded|failed|timed_out> exit_code=<n|none> duration=<s>
stdout:
<...>
stderr:
<...>
```

**Side effects** (applied by the `act` node, not by the tool itself): stores the full
`ExecutionResult` as `last_execution`; clears `files_changed_since_run`; increments
`revision_attempts` if `first_failure_seen` is already set; sets `first_failure_seen` when the
status is `failed` or `timed_out`.
