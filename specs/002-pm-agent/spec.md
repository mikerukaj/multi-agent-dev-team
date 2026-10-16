# Feature Specification: PM Agent and PM-to-Coder Handoff

**Feature Branch**: `002-pm-agent`

**Created**: 2026-10-15

**Status**: Draft

**Input**: User description: "extend the coder agent into a two-agent system by adding a Product Manager (pm) agent, The PM receives the user's high-level requirement, produces a formal technical specification, breaks it into discrete tasks, and hands them off to the coder agent via a structured protocol. Both agents share state through the workflow"

## Clarifications

### Session 2026-10-15

- Q: Should the system pause for the developer to approve the PM agent's specification and task list before any handoff, or run straight through? → A: Fully automatic, with no approval step.
- Q: When all tasks are done, should the system run the finished program once more and report that run at the top level, or count the last task's run as the final run? → A: Run the finished program once more after the last task and report it as a top-level `execution_result`. (Later broadened by FR-016: the final run also happens when handoffs stop after a failed task.)
- Q: When does a task count as completed rather than failed, especially when no code was run for it? → A: Completed if its run succeeded, or if nothing was run and the Coder agent finished normally; failed if the run failed or timed out, or the Coder agent hit its round or revision limit.
- Q: What should the overall outcome say when some tasks finished and a later one failed, or when every task finished but the final run failed? → A: Three outcomes only: completed (every task completed and the final run didn't fail), failed (any task failed or the final run failed, with the reason naming which), declined.
- Q: For each task, should the Coder agent get the whole technical specification, or only the parts that task covers? → A: The covered requirements and acceptance criteria, plus the spec's title, summary and out-of-scope items. (Title and summary are now called name and description; see the planning update below.)
- Q: When someone asks for software that can't be built as a standard-library Python program (for example a React web app or an iOS app), should the PM agent decline it or build the closest Python version? → A: Decline, with a reason naming the limit (standard-library Python programs only).
- Q: Should a single run have an overall limit on model calls, or are the existing per-task limits enough to control cost? → A: No new cap; the existing limits bound the worst case, and it is documented.

### Planning update 2026-10-15

Changed by the `/speckit-plan` input: the PM agent consolidates an over-long task list instead of rejecting it (FR-004a); tasks carry a priority (FR-003); the specification's "title" and "summary" are now "name" and "description", and the task list is part of the specification (FR-002).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Turn a high-level requirement into a specification and working code (Priority: P1)

A developer gives the system a high-level requirement in plain English, such as "Build a
command-line tool that shows the current date and time in Los Angeles, California". The PM agent
writes a formal technical specification for it and breaks the work into an ordered list of
discrete tasks. Each task is handed to the Coder agent in a fixed, structured form. The Coder
agent completes the tasks one at a time in a single shared workspace. The developer gets back one
structured result containing the specification, the task list, what happened on each task, and
the final code.

**Why this priority**: This is the feature. Without the full path from requirement to code there
is no two-agent system. It is also the path the new smoke test exercises.

**Independent Test**: Give the system the Los Angeles date/time requirement. Check that the result
contains a specification, at least one task, a result for every task, and the final code, and
that the final run of the finished program succeeded and printed a date and a time.

**Acceptance Scenarios**:

1. **Given** a configured system, **When** it receives a high-level requirement, **Then** it
   returns one structured result containing the specification, the task list, a result for each
   task, the files in the workspace, and the result of a final run of the finished program, none
   of them empty.
2. **Given** a requirement, **When** the PM agent finishes, **Then** the specification contains
   a name, a description, functional requirements and acceptance criteria, and every task names the
   requirements it covers.
3. **Given** a task list with more than one task, **When** the Coder agent works on a later task,
   **Then** it can see and build on the files written for earlier tasks.
4. **Given** a completed run, **When** the developer reads the result, **Then** each task's
   result states which task it answers, what the Coder agent did, and whether its code ran
   successfully.

---

### User Story 2 - Inspect the handoff between the agents (Priority: P2)

A developer debugging the system wants to see exactly what the PM agent asked the Coder agent to
do and what the Coder agent reported back for each task. Both messages follow a fixed structure,
are checked before they are passed on, and are kept in the final result.

**Why this priority**: The handoff is what makes this a team of agents rather than one long
prompt. A developer who can't see or trust it can't debug either agent. The main flow still
delivers value without this view.

**Independent Test**: Run any requirement and check that each task in the result includes the
exact handoff the Coder agent received and the report it returned, and that both match their
defined structure.

**Acceptance Scenarios**:

1. **Given** a task the PM agent hands off, **When** the Coder agent receives it, **Then** the
   handoff contains the task's identifier, title, description, acceptance criteria and the tasks
   it depends on, plus the specification's name, description and out-of-scope items and only the
   requirements and acceptance criteria the task covers.
2. **Given** a handoff or a report that is missing a required part, **When** the system checks
   it, **Then** the run stops with a clear error instead of passing on an incomplete message.
3. **Given** a completed run, **When** the developer inspects any task, **Then** they can see its
   handoff and report side by side.

---

### User Story 3 - Stop cleanly when a requirement can't be built or a task fails (Priority: P3)

An empty requirement is rejected with a validation error before any work starts. When the
requirement isn't a software request, or is outside what the system can build, the PM agent
declines it with a clear reason before any code is written. When a task fails after
the Coder agent's own revision attempts, the system stops handing off the remaining tasks and
reports which tasks were completed, which one failed, and which were not started.

**Why this priority**: Prevents wasted work and confusing results, but the main flow works without
it.

**Independent Test**: Send an empty requirement and check for a clear validation error. Send a
non-software request and check for a declined result with a reason and no files. Force a task to
fail and check that later tasks are marked not started.

**Acceptance Scenarios**:

1. **Given** an empty or whitespace-only requirement, **When** the system is invoked, **Then** it
   returns immediately with a clear validation error and writes no files.
2. **Given** a request that isn't a software requirement, **When** the PM agent reviews it,
   **Then** the system returns a declined result explaining why, with no tasks handed off and no
   files written.
3. **Given** a task whose code still fails after the Coder agent's revision attempts, **When** the
   Coder agent reports back, **Then** no further tasks are handed off, and the result marks that
   task failed and every later task not started.
4. **Given** a request for software that can't be built as a standard-library Python program,
   such as "Build a React web app for my recipes", **When** the PM agent reviews it, **Then** the
   system returns a declined result whose reason says only standard-library Python programs can
   be built, with no tasks handed off and no files written.
5. **Given** an early task that only adds supporting code and has no program to run yet, **When**
   the Coder agent finishes it normally, **Then** the task is marked completed and the next task
   is handed off.

---

### Edge Cases

- The PM agent produces more tasks than the configured maximum: it consolidates them (FR-004a).
  If the list is still too long after the allowed attempts, the run stops with a clear error
  before any task is handed off.
- A task depends on a task that comes after it, on itself, or on a task that doesn't exist: the
  task list is rejected before any handoff.
- A specification requirement that no task covers: the task list is rejected before any handoff.
- A software request the system can't build as a standard-library Python program (a web front
  end, a mobile app, something needing third-party packages): declined with a reason naming the
  limit (FR-012), never swapped for a Python stand-in.
- A requirement that fits in a single task: the system still produces a specification and a task
  list with one task, and runs it through the same handoff.
- The Coder agent's file tools stay limited to the shared workspace for every task, exactly as in
  the Coder-only feature.
- The language model service is unavailable or returns an unusable answer during the PM agent's
  work or any task: the run fails with a clear, actionable error that names the stage it failed in.
- The existing single-task Coder agent entry point is still used directly: it keeps working as
  before, with its own new, empty workspace.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST accept a single high-level software requirement written in natural
  language.
- **FR-002**: The PM agent MUST produce a formal technical specification before any task is handed
  off. The specification MUST contain at least: a name, a description, functional requirements
  (each with an identifier), acceptance criteria (each linked to the requirement it checks),
  assumptions, out-of-scope items, and the list of tasks (FR-003).
- **FR-003**: The PM agent MUST break the specification into an ordered list of discrete tasks.
  Each task MUST have an identifier, a title, a description, acceptance criteria, a priority
  (high, medium or low), the specification requirements it covers, and the identifiers of the
  tasks it depends on. Priority describes importance; tasks are always handed off in list order.
- **FR-004**: The task list MUST be checked before any handoff. It MUST be rejected with a clear
  error if it is empty, has a dependency on an unknown, later or same task, or leaves any
  specification requirement uncovered.
- **FR-004a**: If the PM agent produces more tasks than the configured maximum (default 8), it
  MUST consolidate them into at most that many tasks before any handoff, keeping every
  requirement covered. Consolidation MUST be attempted at most a configured number of times
  (default 2); if the list is still too long, the run MUST stop with a clear error before any
  handoff.
- **FR-005**: The system MUST hand tasks to the Coder agent one at a time, in list order, using a
  fixed handoff structure that contains the task's fields (FR-003) plus this context from the
  specification: its name, description and out-of-scope items, and the full text of the functional
  requirements and acceptance criteria the task covers. Requirements the task doesn't cover MUST
  NOT be included.
- **FR-006**: For each task, the Coder agent MUST return a fixed report structure that names the
  task it answers and contains the Coder agent's existing result: code, explanation, plan and
  execution result.
- **FR-007**: Every specification, task list, handoff and report MUST be checked against its
  defined structure before it is passed on or stored. A message missing a required part MUST stop
  the run with an error, not be passed on in part.
- **FR-008**: Both agents MUST work from one shared workflow state that holds the requirement, the
  specification, the task list, each task's status (not started, in progress, completed, failed),
  and each task's handoff and report. Each agent MUST read the inputs it needs from this state
  rather than from a separate copy.
- **FR-009**: All tasks for one requirement MUST share one new, empty workspace, so later tasks can
  read and change files written by earlier tasks. If the caller supplies a workspace path that
  already contains files, the system MUST reject it with a clear error before any model call.
- **FR-010**: A task MUST be marked completed when its report shows a successful run, or when no
  code was run and the Coder agent finished normally. It MUST be marked failed when its report
  shows a failed or timed-out run, when the Coder agent stopped at its round or revision limit, or
  when the Coder agent rejected the task as not a coding task (its stop reason is `rejected`).
  "Declined" is reserved for the PM agent turning down a requirement (FR-012).
- **FR-010a**: When a task is marked failed, the system MUST stop handing off tasks, mark every
  later task not started, and still return the full structured result.
- **FR-011**: The system MUST return one structured result containing exactly these top-level
  parts:
  - **specification**: the PM agent's specification (FR-002);
  - **tasks**: every task, each with its status, its handoff and, if it ran, its report;
  - **code**: every file in the shared workspace when the run ends, each with its path and full
    contents;
  - **execution_result**: the result of one final run of the finished program (FR-016), in the
    same form as the Coder agent's execution result;
  - **outcome**: one of three values, with a short reason:
    - **completed**: every task was completed and the final run did not fail or time out;
    - **failed**: a task failed, or the final run failed or timed out; the reason names which;
    - **declined**: the PM agent declined the requirement (FR-012).
- **FR-012**: The system MUST reject an empty or whitespace-only requirement with a clear
  validation error before any model call. The PM agent MUST decline, with a clear reason, any
  request that isn't for software, and any software request that can't be built as a
  standard-library Python program (for example a web front end, a mobile app, or anything needing
  third-party packages). The reason for the second kind MUST name that limit. The PM agent MUST
  NOT substitute a different kind of program. In both cases no task is handed off and no file is
  written.
- **FR-013**: The existing single-task Coder agent entry point, its result structure and its smoke
  test MUST keep working unchanged.
- **FR-014**: The project MUST include a smoke test that sends the system the requirement "Build a
  command-line application that displays the current date and time in Los Angeles, California"
  and asserts that the result has a non-empty specification, at least one task, a report for every
  completed task, non-empty code, a "completed" outcome, and a top-level `execution_result` that
  reports a successful run whose output contains a date and a time. When the language model
  service isn't configured, this test MUST be reported as skipped with a stated reason.
- **FR-015**: The PM agent MUST use the same long-term memory as the Coder agent: it MUST look up
  relevant past context before each model call and store its specifications and task lists there.
- **FR-016**: When handoffs end, whether every task was completed or the run stopped after a
  failed task, the system MUST run the program's entry point once in the shared workspace, under
  the same isolation and time limit as the Coder agent's runs, and report it as the top-level
  `execution_result`. This run MUST NOT call the language model. When the requirement was
  declined or the workspace has no entry point, the `execution_result` MUST be marked as not run.

### Key Entities

- **Requirement**: The high-level request from the developer. Has the requirement text.
- **Technical Specification**: The PM agent's formal description of what to build: name,
  description, numbered functional requirements, acceptance criteria, assumptions, out-of-scope
  items and the task list.
- **Task**: One discrete unit of work from the specification: identifier, title, description,
  acceptance criteria, priority, covered requirements, dependencies and status.
- **Task Handoff**: The fixed message the PM side sends to the Coder agent for one task: the task's
  fields, plus the specification's name, description and out-of-scope items and the requirements
  and acceptance criteria the task covers.
- **Task Report**: The fixed message the Coder agent returns for one task: the task identifier and
  the Coder agent's result (code, explanation, plan, execution result).
- **Workflow State**: The single shared record both agents read from and write to during a run:
  requirement, specification, tasks with statuses, handoffs and reports.
- **Team Result**: The single structured answer returned to the developer: specification, tasks,
  code, the final run's execution result, and outcome.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The smoke test requirement returns a result with every required part filled in and
  a "completed" outcome on 100% of runs where the language model service is available.
- **SC-002**: For the smoke test requirement, the final code runs successfully and prints the
  current Los Angeles date and time in at least 9 out of 10 runs. This is checked by hand before
  release; the single smoke test run is the merge gate.
- **SC-003**: A developer receives the full result for the smoke test requirement in under 10
  minutes.
- **SC-004**: 100% of handoffs and reports in a result match their defined structure, and 0
  incomplete messages are ever passed between the agents.
- **SC-005**: Every specification requirement in a completed result is covered by at least one
  task (100% coverage).
- **SC-006**: When a task fails, 0 later tasks are handed off, and 100% of tasks in the result
  show their correct status.
- **SC-007**: The Coder-only smoke test from the earlier feature still passes with no changes to
  its assertions.

## Assumptions

- This feature adds only the PM agent and the PM-to-Coder handoff. The QA agent, and any review of
  the Coder agent's work by the PM agent, are out of scope.
- The run is fully automatic: there is no human approval step between the specification, the task
  list and the handoffs (confirmed 2026-10-15). An approval step may be added in a later feature.
- Tasks run one at a time, in order. Running tasks in parallel is out of scope.
- A failed task is not re-planned or re-assigned by the PM agent; the Coder agent's own limit of 3
  revision attempts per task still applies.
- Generated code is Python, runs locally in the shared workspace with only the standard library
  and already-installed packages, as in the Coder-only feature.
- The system is invoked by a developer or a test from code or the command line; a user interface
  is out of scope.
- The maximum number of tasks (default 8) and of consolidation attempts (default 2) are defaults
  that can be changed in configuration.
- There is no run-wide limit on model calls or tokens (confirmed 2026-10-15). The existing limits
  bound the worst case at 99 model calls per requirement: 1 specification call, up to 2
  consolidation calls, and up to 12 Coder calls per task (1 plan, 10 rounds, 1 explanation) for
  up to 8 tasks. The project documentation MUST state this worst case.
- The Coder-only rule that every run starts in a new, empty workspace still holds for the whole
  requirement; it is the tasks within one requirement that share the workspace.
- Both smoke tests call the real language model service and need valid credentials to run.
