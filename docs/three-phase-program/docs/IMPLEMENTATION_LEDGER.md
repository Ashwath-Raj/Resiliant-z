# Implementation Ledger

Use this as the living sign-off record. Do not mark an item complete solely because its file exists.

## Session 1 — Repository and contract baseline

**Status: `done` (Session 1 acceptance passed; Phase I is not signed off).**

| Work item | Status | Evidence |
|---|---|---|
| Record branch, HEAD, dirty state, and preserve existing work | `done` | Baseline: `feat/local-discrete-event`, `1fa126c7fa0da627d8513de5b71527d8ca267412`; the pre-edit patch, untracked-file archive, status, and artifact checksums are in session state under `files/session1-pre-edit/`. |
| Capture the pre-change test and quality baseline | `done` | `.venv/bin/python -m pytest -q`: 31 passed; Ruff check/format, compileall, and `git diff --check` passed. |
| Define the versioned manifest/result contract | `done` | [models.py](../../../src/resiliant_z/models.py), [run-manifest.v1.schema.json](../schemas/run-manifest.v1.schema.json), [run-result.v1.schema.json](../schemas/run-result.v1.schema.json), and [test_contracts.py](../../../tests/test_contracts.py). |
| Preserve legacy payload reads and represent incomplete results honestly | `done` | Round-trip, legacy-input, invalid-field, incomplete CSV, and unmeasured-metric tests in [test_contracts.py](../../../tests/test_contracts.py). |
| Keep existing experiment artifacts unchanged | `done` | SHA-256 checksums for all 54 pre-existing artifact files were captured before edits and verified unchanged after testing. |
| Session 1 verification | `done` | `.venv/bin/python -m pytest -q`: 35 passed; Ruff check/format, compileall, whitespace, JSON syntax, and artifact checksum checks passed. |

The current local backends now emit `deadlock_events: null`; existing experiment files are intentionally preserved byte-for-byte and may still contain legacy integer values. `scenario_version` is inferred from a trailing `_vN` in existing scenario IDs when no explicit version is supplied. A scenario configuration hash remains optional until a versioned config file exists. Older/manual manifests may still have `git_sha: "unknown"`; normal planner-created manifests record the current Git SHA.

**Gate decision:** Session 1 passes. The Phase I exit gate remains `not_started` pending Sessions 2–5 and review; no Session 2 work has begun.

## Phase I — local engine/contracts

- [x] Backup current local worktree and record HEAD/dirty state.
- [x] Establish pre-change test/lint baseline.
- [x] Review objective function and metric definitions.
- [ ] Extract one canonical, pure policy decision function.
- [ ] Make local simulator and future adapter share that function.
- [x] Version run/manifest/result schemas and units.
- [x] Test paired seeds, deterministic outputs and censored waits.
- [x] Audit deadlock/collision fields as measured vs unmeasured.
- [x] Preserve and label existing stress/sensitivity artifacts.
- [ ] Phase I review approved.

## Phase II — discovery/evidence

- [ ] Telemetry schema, aggregation and data-quality flags.
- [ ] Model/reality-gap detector with documented threshold.
- [ ] Offline fixture provider; remote provider disabled by default.
- [ ] Hypothesis validation (schema, whitelist, bounds, output size).
- [ ] Semantic experiment compiler and immutable manifests.
- [ ] Separate discovery, validation and replay seeds.
- [ ] Registry handles failures/timeouts/incomplete runs.
- [ ] Paired effect + uncertainty report and multiplicity note.
- [ ] Independent held-out validation gate.
- [ ] Versioned knowledge records with provenance.
- [ ] Policy updates are allowlisted, bounded and replay-tested.
- [ ] Phase II review approved.

## Phase III — Isaac readiness, not execution

- [ ] Existing adapter contract reused; no parallel result schema.
- [ ] Isaac imports lazy; CPU CI independent of Isaac package.
- [ ] Fake backend tests for valid, malformed and failed outputs.
- [ ] Versioned warehouse scene configuration.
- [ ] Robot asset selection deferred until actual host/assets are known.
- [ ] Articulation/controller interface specified; no pose-animation shortcut.
- [ ] Telemetry fields include commanded/observed state and task lifecycle.
- [ ] Contact/collision/deadlock claims gated on implemented instrumentation.
- [ ] Separate runtime/environment options documented.
- [ ] Official release compatibility checked against provided host.
- [ ] Run/asset/scene hashes included in provenance.
- [ ] Installation, downloads and simulator execution still disabled.
- [ ] Phase III code/document review approved.

## Authorized runtime stage — intentionally not started

- [ ] User explicitly authorizes host access and runtime.
- [ ] Host/GPU/driver/OS/runtime requirements verified.
- [ ] Approved Isaac installation verified independently.
- [ ] One robot / one junction test.
- [ ] Two-robot test.
- [ ] Ten-robot test.
- [ ] 20–35 robot scale-up, only if prior gates pass.
- [ ] Artifact validation and limitations reviewed.
