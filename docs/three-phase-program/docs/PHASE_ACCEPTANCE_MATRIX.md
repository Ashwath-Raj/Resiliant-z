# Phase Acceptance Matrix

| Gate | Phase I: Local engine | Phase II: Discovery/evidence | Phase III: Isaac readiness |
|---|---|---|---|
| Reproducible manifest | Required | Required | Required, extended with runtime/assets |
| Canonical route-decision function | Implemented and tested | Reused; not duplicated | Called by the Isaac control adapter |
| Local CPU backend | Required | Default backend | Regression reference |
| Fake/provider tests | N/A | Required; no real API in CI | Required for backend contract |
| Hypothesis validation | Not required for simulator unit tests | Strict schema, whitelist and range checks | Same validated manifest only |
| Discovery/validation separation | Existing experiment tests preserved | Candidate stage keeps data provenance | Independent held-out validation; same rule for actual simulator studies |
| Failure data | Explicit | Explicit, never counted as evidence | Explicit simulator failure/incomplete episode |
| Deadlock/collision metrics | Unmeasured if unsupported | Never fabricated | Only measured with a documented detector |
| Cloud call/spend | Disabled | Disabled by default; explicit opt-in | Disabled unless separately authorized |
| Knowledge promotion / policy replay | N/A | Candidate records only | Validated knowledge and bounded paired replay |
| Isaac installed/launched | No | No | **No: readiness only** |
| Main evidence label | Local discrete-event, not Isaac | Local discrete-event unless real Isaac data exists | Isaac results only after later approved real execution |

## Required verification commands at phase gates

These are acceptance commands to be used during development, not commands executed by this bundle. Run from the project root after changes have been applied and reviewed:

```bash
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src tests
 git diff --check
 git status -sb
```

Do not use `ruff format src tests` across the entire repository just to pass a gate if it causes unrelated file churn. Format touched files intentionally, review the diff, then run format check.
