<!--
Sync Impact Report
==================
Version change: (unratified template) → 1.0.0
Bump rationale: Initial ratification; all placeholders replaced with project-specific content.

Principles defined:
- [PRINCIPLE_1_NAME] → I. Clean Code
- [PRINCIPLE_2_NAME] → II. Structured Agent Outputs
- [PRINCIPLE_3_NAME] → III. Smoke Test Gate (NON-NEGOTIABLE)
- [PRINCIPLE_4_NAME] → IV. Mandated Technology Stack
- [PRINCIPLE_5_NAME] → V. Simplicity and Explicit Configuration

Added sections:
- Technology Constraints (was [SECTION_2_NAME])
- Development Workflow and Quality Gates (was [SECTION_3_NAME])

Removed sections: none

Dependent templates: not modified by this command (they read the constitution at runtime).

Deferred TODOs: none
-->

# Multi-Agent Dev Team Constitution

## Core Principles

### I. Clean Code

All code in this repository MUST be written to be read by the next engineer first.

- Names MUST describe intent: modules, classes, functions and variables use full words, not
  abbreviations or single letters (loop indices excepted).
- Each function MUST do one thing. Functions longer than ~40 lines or with more than 4
  parameters MUST be split or justified in review.
- Public functions, classes and LangGraph nodes MUST have type hints and a docstring stating
  purpose, inputs and outputs.
- No dead code, commented-out code, or unused imports may be merged.
- No magic values: prompts, model IDs, collection names, thresholds and limits MUST live in
  named constants or configuration, not inline literals.
- Duplicated logic appearing in three or more places MUST be extracted into a shared helper.
- Errors MUST be handled explicitly: no bare `except:`, no silently swallowed exceptions.
  Failures from the LLM or memory backend MUST surface with an actionable message.
- Code MUST pass the project linter and formatter (Ruff) with zero warnings before merge.

Rationale: an agent system is hard to debug when behavior hides in long, loosely named
functions. Small, typed, well-named units keep agent behavior traceable.

### II. Structured Agent Outputs

Every agent (PM, Coder, QA and any added later) MUST return a typed, validated structured
output, not free-form text.

- Each agent's output MUST be defined as a Pydantic model that declares every required field.
- The LLM response MUST be parsed and validated against that model before it enters LangGraph
  state. Validation failures MUST raise, not be coerced into partial results.
- Output schemas are contracts: changing a required field is a breaking change and MUST be
  called out in the PR description.

Rationale: downstream agents and tests can only rely on fields that are guaranteed to exist.

### III. Smoke Test Gate (NON-NEGOTIABLE)

The project MUST maintain, at minimum, one smoke test that exercises the real agent path.

- The smoke test MUST invoke the compiled LangGraph agent graph with a short coding task
  (for example, "write a Python function that reverses a string").
- It MUST assert that the returned structured output validates against the agent's output
  schema and that every required field is present and non-empty.
- It MUST run under `pytest` and live under `tests/`.
- When the LLM API key is not configured, the test MUST be reported as skipped with an explicit
  reason; it MUST NOT silently pass.
- No change that touches agents, graph wiring, prompts, or memory may merge while the smoke
  test fails.

Rationale: a single end-to-end check catches broken wiring, prompt regressions and schema
drift that unit tests on isolated nodes cannot.

### IV. Mandated Technology Stack

The following choices are fixed and MUST NOT be substituted without a constitution amendment:

- **Agent framework**: LangGraph. All agent orchestration, state and control flow MUST be
  expressed as LangGraph graphs and nodes; no parallel ad-hoc orchestration loops.
- **LLM**: Claude Sonnet 5.5 (model ID `claude-sonnet-5-5`) via the Anthropic API for all agents.
- **Memory backend**: Chroma. All persistent agent memory and retrieval MUST go through Chroma;
  no second vector store or ad-hoc file-based memory.

Rationale: one framework, one model and one memory store keep behavior reproducible and
avoid integration sprawl.

### V. Simplicity and Explicit Configuration

- Build only what a current spec requires (YAGNI). New abstractions MUST be justified by a
  present need, not a hypothetical one.
- Secrets (such as `ANTHROPIC_API_KEY`) MUST come from environment variables and MUST NOT be
  committed. `.env.example` MUST list every required variable without real values.
- The model ID and Chroma connection settings MUST be defined in exactly one configuration
  location and imported everywhere else.

Rationale: a single source of configuration makes swapping environments safe and prevents
accidental leaks of credentials.

## Technology Constraints

- Language: Python 3, with dependencies pinned in `requirements.txt`.
- Orchestration: LangGraph (Principle IV).
- LLM: Claude Sonnet 5.5, `claude-sonnet-5-5` (Principle IV).
- Memory: Chroma (Principle IV).
- Testing: `pytest`.
- Lint and format: Ruff.
- Runtime packaging: the repository's `Dockerfile` and `docker-compose.yml` MUST be able to run
  the agent graph and its Chroma dependency.

## Development Workflow and Quality Gates

A change MAY merge only when all of the following hold:

1. Ruff lint and format checks pass with zero warnings.
2. The full `pytest` suite passes, including the smoke test from Principle III.
3. Any change to an agent output schema is called out in the PR description.
4. Reviewers have checked the change against every Core Principle; any deviation is documented
   with a justification in the PR.

## Governance

- This constitution supersedes other project practices and conventions. Where they conflict,
  the constitution wins.
- Amendments MUST be made via a pull request that edits this file, updates the Sync Impact
  Report, and states the reason for the change.
- Versioning follows semantic versioning:
  - MAJOR: removing or redefining a principle, or changing the mandated stack.
  - MINOR: adding a principle or section, or materially expanding guidance.
  - PATCH: clarifications and wording fixes with no change in meaning.
- Every PR review MUST verify compliance with this constitution. Added complexity MUST be
  justified in the PR.

**Version**: 1.0.0 | **Ratified**: 2026-10-09 | **Last Amended**: 2026-10-09
