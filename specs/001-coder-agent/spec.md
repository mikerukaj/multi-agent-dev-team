# Feature Specification: Coder Agent

**Feature Branch**: `001-coder-agent`

**Created**: 2026-10-09

**Status**: Draft

**Input**: User description: "Build a single, fully functional Coder agent that can accept a natural language coding task, plan its approach, write code using the file system tools, and return structured output. The agent should return structured output containing: the generated code, a natural language explanation, the execution plan used, and the result of running the code. The minimum basic smoke test will invoke the agent with the prompt "Write a python application that displays the current date and time in Los Angeles, California" and assert the structured output has the correct fields."

## Clarifications

### Session 2026-10-09

- Q: How strongly should the code the agent generates be isolated from your machine when the agent runs it? → A: Run it as a separate process from the workspace folder, without secrets in its environment and with a timeout; the project's container is the real security boundary.
- Q: Should the smoke test also fail when the generated Los Angeles program doesn't run successfully, or only when a result field is missing or empty? → A: Check the four fields, and also that the run succeeded and printed a date and time.
- Q: How long should the agent's long-term memory of past tasks be kept, and how is it cleared? → A: Keep it indefinitely; provide a command to wipe it.
- Q: Should the agent be able to work on code that already exists in a folder you point it at, or should it always start from an empty folder? → A: Always a new, empty folder per task; `code` lists every file in it.
- Q: How should the "at least 9 of 10 runs succeed" target (SC-002) be checked, given each run calls the paid model? → A: By hand before release; no automated repeat runs. The single smoke test is the merge gate.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Turn a coding task into working, explained code (Priority: P1)

A developer gives the Coder agent a short coding task in plain English, such as "Write a python
application that displays the current date and time in Los Angeles, California". The agent works
out a step-by-step plan, writes the code to files in its workspace, runs the code, and hands back
one structured result containing the code, a plain-language explanation, the plan it followed,
and what happened when the code ran.

**Why this priority**: This is the whole feature. Without it there is no agent. It is also the
path the project's mandatory smoke test exercises.

**Independent Test**: Give the agent the Los Angeles date/time task and check that the result
contains all four parts (code, explanation, plan, run result), each filled in. "Run result" in
this spec means the `execution_result` field.

**Acceptance Scenarios**:

1. **Given** a configured agent, **When** it receives "Write a python application that displays
   the current date and time in Los Angeles, California", **Then** it returns a structured result
   with the generated code, an explanation, the execution plan and the run result, none of them
   empty.
2. **Given** the same task, **When** the result is returned, **Then** the code it describes exists
   as files in the agent's workspace, and the file contents match the code in the result.
3. **Given** the same task, **When** the result is returned, **Then** the run result shows the
   program ran successfully and its output contains a date and time for Los Angeles.
4. **Given** any completed task, **When** the result is returned, **Then** the plan lists the
   ordered steps the agent actually took.

---

### User Story 2 - Report honestly when the code does not work (Priority: P2)

When the code the agent writes fails to run (an error, a crash, or running too long), the agent
tries to fix it a limited number of times. If it still fails, it returns the same structured
result with the failure clearly reported, rather than claiming success or returning nothing.

**Why this priority**: Developers need to trust the result. A failure that looks like success is
worse than no answer.

**Independent Test**: Give the agent a task whose code cannot succeed in the environment (for
example, one that needs a resource that is not available) and check that the result marks the run
as failed and includes the error output.

**Acceptance Scenarios**:

1. **Given** generated code that raises an error when run, **When** the agent finishes, **Then**
   the run result marks the run as failed and includes the error output.
2. **Given** generated code that fails on the first run, **When** the agent revises it, **Then**
   it makes at most 3 revision attempts before returning, and the plan records each attempt.
3. **Given** generated code that runs longer than the time limit, **When** the limit is reached,
   **Then** the run is stopped and the run result reports a timeout.

---

### User Story 3 - Reject tasks the agent cannot act on (Priority: P3)

When the task is empty, not a coding request, or asks for something outside the agent's scope,
the agent returns a clear message saying why it did not proceed, without writing or running any
code.

**Why this priority**: Prevents wasted work and confusing results, but the main flow works without
it.

**Independent Test**: Send an empty task and check that it raises a clear validation error. Send
a non-coding request and check that it returns a rejected result explaining the refusal. In both
cases, check that no files were written.

**Acceptance Scenarios**:

1. **Given** an empty or whitespace-only task, **When** the agent is invoked, **Then** it returns
   immediately with a clear validation error and writes no files.
2. **Given** a request that is not a coding task, **When** the agent is invoked, **Then** it
   returns a result explaining why it did not proceed, with the run result marked as not run.

---

### Edge Cases

- A task that needs more than one file: the result lists every file written, each with its path
  and contents.
- The agent's file tools are asked to read or write outside the workspace: the request is refused
  and the refusal is recorded in the plan's trace.
- The generated program itself writes outside the workspace when it runs: this is NOT prevented
  (see FR-005a); the project's container is the boundary.
- Generated code that tries to read the language model credentials from its environment: they
  are not there.
- Code that waits for keyboard input: it receives no input and the run either finishes or hits the
  time limit; it never hangs the agent.
- Very large program output: the run result keeps a bounded amount of output and notes that it was
  cut short.
- The language model service is unavailable or returns an unusable answer: the agent fails with a
  clear, actionable error instead of returning a partial result.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The agent MUST accept a single coding task written in natural language.
- **FR-002**: The agent MUST produce an ordered execution plan before writing any code.
- **FR-003**: The agent MUST write the code it generates to files inside a dedicated workspace
  directory, using file system tools. Each task MUST get its own new, empty workspace; if the
  caller supplies a workspace path that already contains files, the agent MUST reject it with a
  clear error before doing any work. Working on existing code is out of scope.
- **FR-004**: The agent's file tools MUST NOT read, create, change or delete files outside the
  task's workspace directory. This applies to the agent's own tools, not to the generated program
  while it runs (see FR-005a).
- **FR-005**: The agent MUST run the generated code and capture whether it succeeded, its exit
  status, its standard output and its error output.
- **FR-005a**: The agent MUST run generated code as a separate process, started in the workspace
  folder, with no keyboard input and with no secrets (such as the language model credentials) in
  its environment. Stronger isolation (blocking network access, a container per run) is out of
  scope; the project's container is the security boundary.
- **FR-006**: The agent MUST stop any run that exceeds a time limit (default 30 seconds) and report
  it as a timeout.
- **FR-007**: The agent MUST return one structured result containing exactly these top-level
  fields:
  - **code**: every file in the task's workspace when the agent finishes, each with its path
    and full contents;
  - **explanation**: a plain-language description of what the code does and how to run it;
  - **plan**: the ordered steps the agent followed, including any revision attempts;
  - **execution_result**: success or failure, exit status, standard output, error output, and
    whether the run timed out or was not run.
- **FR-008**: The structured result MUST be checked against its definition before it is returned;
  a result missing a required field MUST be treated as an error, not returned.
- **FR-009**: When the code fails to run, the agent MUST make no more than 3 revision attempts
  before returning its final result.
- **FR-010**: The agent MUST report a failed or timed-out run as failed in the result; it MUST NOT
  report success for a run that did not succeed.
- **FR-011**: The agent MUST reject empty tasks and non-coding requests with a clear reason,
  without writing or running code.
- **FR-012**: The project MUST include a smoke test that sends the agent the task "Write a python
  application that displays the current date and time in Los Angeles, California" and asserts that
  the result contains the code, explanation, plan and execution_result fields, each non-empty.
  It MUST also assert that the execution result reports a successful run and that the program's
  output contains a date and a time.
- **FR-012a**: The agent's long-term memory MUST persist between runs with no automatic expiry,
  and the project MUST provide a single command that wipes it completely. Tests MUST use a
  separate, temporary memory so they never read from or add to the developer's memory.
- **FR-013**: When the language model service is not configured, the smoke test MUST be reported
  as skipped with a stated reason; it MUST NOT pass silently.

### Key Entities

- **Coding Task**: The natural language request from the developer. Has the task text.
- **Execution Plan**: The ordered list of steps the agent intends to take and actually took,
  including revision attempts.
- **Generated File**: A file the agent wrote. Has a path relative to the workspace and its full
  contents.
- **Execution Result**: The outcome of running the code: success flag, exit status, standard
  output, error output, timed-out flag, and a not-run state for rejected tasks.
- **Agent Result**: The single structured answer returned to the developer, combining generated
  files, explanation, plan and execution result.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The smoke test task returns a result with all four required fields filled in on
  100% of runs where the language model service is available.
- **SC-002**: For the smoke test task, the generated program runs successfully and prints the
  current Los Angeles date and time in at least 9 out of 10 runs. This is checked by hand before
  release, not by an automated test; the single smoke test run is the merge gate.
- **SC-003**: A developer receives the full result for the smoke test task in under 2 minutes.
- **SC-004**: 100% of failed or timed-out runs are reported as failed in the result.
- **SC-005**: 0 files are created or changed outside the workspace by the agent's file tools
  across all test runs, including attempts using `..`, absolute paths and symbolic links.
- **SC-006**: A developer can read the explanation and run the generated code themselves without
  any other guidance.

## Assumptions

- This feature delivers only the Coder agent. The PM and QA agents, and coordination between
  agents, are out of scope.
- Generated code is Python for this version, matching the smoke test task. Other languages are out
  of scope.
- The agent is invoked by a developer or a test from code; a user interface is out of scope.
- Generated code runs locally in the project's environment, inside the agent's workspace, with
  only the standard library and already-installed packages. Installing new packages is out of
  scope.
- The agent keeps a short-term memory of its most recent steps and a long-term memory of past
  context that persists between runs, and looks up relevant past context before each reasoning
  step. (Updated 2026-10-09 during planning; this replaces the earlier "no memory between runs"
  assumption.)
- The agent works in rounds of reasoning and acting, capped at 10 rounds per task; the
  3-revision limit applies within that cap.
- The 30-second run limit, the 3-revision limit and the output size bound are defaults that can
  be changed in configuration.
- The smoke test calls the real language model service and needs valid credentials to run.
