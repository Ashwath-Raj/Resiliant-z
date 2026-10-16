# Local Coding Agent — Execution Instructions

Use this prompt only in the local repository opened in VS Code/Codex or another code agent that can read and edit the actual working tree. The source code must be inspected before edits; this document is not a substitute for inspecting it.

## Mission

Implement the existing RESILIANT-Z codebase according to `docs/THREE_PHASE_IMPLEMENTATION_PLAN.md` and `docs/SESSION_BY_SESSION_EXECUTION.md`, one session at a time. Preserve the supplied product/research objective and architecture: **LLM proposes, deterministic software validates, simulation supplies evidence, statistics decides, validated knowledge is operationalized, paired replay measures effect.**

## Hard constraints

- Do not use or run the earlier Isaac fast-track adapter/scaffold as the primary simulator implementation.
- Do not install Isaac Sim, download assets, launch Isaac Sim, start an Isaac runtime, submit Nebius Jobs, make paid API calls or execute a GPU simulation. Stop before real Isaac execution.
- Do not overwrite, reset, clean, rebase or discard user changes. Begin by recording `git status -sb`, branch, HEAD and baseline tests. If pre-existing edits are present, preserve them and work in a new branch only after checking whether that branch already exists.
- Do not mark any session complete without direct code references and passing tests.
- Do not invent project APIs. Inspect the current implementation and reuse existing interfaces. Avoid duplicate policy engines, duplicate result schemas, parallel storage systems and unnecessary dependencies.
- Do not broadly format the entire project. Format touched Python files only and inspect diffs.
- Keep cloud/model-provider paths disabled by default and test them with fixtures/mocks only.
- No LLM may command robot velocity, emit executable code, approve discoveries, change policy limits or override fallback logic.
- Keep `deadlock_events`/collision fields unmeasured unless the relevant detector exists. Never convert failures/timeouts/missing data to zero or success.
- Keep the local-model evidence label exactly `LOCAL DISCRETE-EVENT FLEET MODEL — NOT ISAAC SIM`. Do not label shadow estimates as Isaac measurements.

## Required workflow

1. Read the implementation plan, session matrix, acceptance matrix, architecture/trust-boundaries and supplied 15-session source plan.
2. Inventory existing modules/tests/CLI and map them to Sessions 1–15. Identify what is already complete; do not duplicate it. Create/update `docs/IMPLEMENTATION_LEDGER.md` with statuses `not_started`, `in_progress`, `blocked`, `done`, and links to evidence.
3. Establish baseline: run only lint/test/compile/whitespace checks and small unit tests. Do not run long experimental sweep commands unless specifically required for a regression and the user has authorized it.
4. Implement Session 1 as the smallest coherent diff, test, review the diff and update the ledger. Do not begin the next session if the current gate is broken.
5. Continue sessions in order, grouping work into the three phases defined by the plan. Prefer test-first changes and backward-compatible migrations. Add fixture tests for errors and incomplete states as well as success.
6. At each phase gate, run the required local quality checks and review `git diff --stat`, `git diff --check`, `git status -sb` and the full diff. Summarize passing/failing tests, changed files, known limitations and next session. Never claim a test or integration was run when it was not.
7. Phase III ends with a tested offline adapter contract, versioned scenario and run bundle, artifact validation, and host-readiness docs. All Isaac-specific imports must be lazy/optional. Execution must default to disabled.
8. Do not commit or push automatically. Provide a final review summary with exact commands and recommended commit boundaries; wait for explicit authorization before modifying remote Git state.

## Acceptance commands

Use these only if the project has the corresponding tools installed; don't install packages automatically:

```bash
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src tests
git diff --check
git status -sb
```

If a command fails, diagnose and fix the cause; do not skip the gate. If a command is unavailable, report it and use the already-configured project equivalent. Do not execute the existing full experiment/benchmark CLIs as part of a basic test pass.

## First response required from the agent

Report the real baseline inventory and exact Session 1 files/tests before editing. Then implement Session 1 and show the diff. Work sequentially; no one-shot rewrite of the repository.
