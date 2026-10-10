# Quickstart: Validate the Coder Agent

How to prove the feature works end to end. Contracts: [coder-agent-api.md](contracts/coder-agent-api.md),
[tools.md](contracts/tools.md). Models: [data-model.md](data-model.md).

## Prerequisites

- Python 3.12
- An Anthropic API key with access to `claude-opus-5-5`
- Network access on first run (Chroma downloads its embedding model, about 80 MB)

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then set ANTHROPIC_API_KEY in .env
```

## 1. Lint (quality gate)

```bash
ruff check . && ruff format --check .
```

**Expected**: no warnings.

## 2. Unit tests (no API key needed)

```bash
pytest tests/unit -q
```

**Expected**: all pass. Covers path confinement, `exec_python` timeout and input waits, output
truncation, buffer windowing, and graph routing for the iteration cap (10), revision cap (3) and
rejection.

## 3. Smoke test (real model)

```bash
pytest -m smoke -v
```

**Expected**: `test_smoke_coder_agent` passes. Without `ANTHROPIC_API_KEY` it shows as
**SKIPPED** with reason `ANTHROPIC_API_KEY not set` (never a silent pass).

## 4. Manual run

```bash
python -m agents.coder_agent "Write a python application that displays the current date and time in Los Angeles, California"
```

**Expected**:

- JSON printed to stdout with `code`, `explanation`, `plan` and `execution_result`.
- `execution_result.status` is `succeeded` and `stdout` shows a Los Angeles date and time
  (PDT or PST).
- `plan.iterations` ≤ 10 and `plan.stop_reason` is `completed`.
- Files exist under `workspace/<run_id>/` and match the `code` entries.
- Completes in under 2 minutes (spec SC-003).

## 5. Memory check

Run step 4 twice, then:

```bash
python -m memory.inspect --last 10
```

**Expected**: records from both runs (`kind` = task, plan, thought, observation, result). The
second run's prompts include a "Relevant past context" block (visible with `LOG_LEVEL=DEBUG`).

To wipe all long-term memory (spec FR-012a):

```bash
python -m memory.inspect --wipe          # asks for confirmation
python -m memory.inspect --wipe --yes    # no prompt
```

**Expected**: `python -m memory.inspect --last 10` then shows no records.

## 5a. Workspace check

```bash
mkdir -p /tmp/not-empty && touch /tmp/not-empty/existing.py
python -m agents.coder_agent "Write hello world" --workspace /tmp/not-empty
```

**Expected**: exits 1 with an `InvalidWorkspaceError` message and no model call (spec FR-003).

## 6. Failure path

```bash
python -m agents.coder_agent "Write a python script that sleeps for 120 seconds then prints done"
```

**Expected**: `execution_result.status` is `timed_out`, `success` is `false`, and the run stops
by the configured timeout rather than hanging.
