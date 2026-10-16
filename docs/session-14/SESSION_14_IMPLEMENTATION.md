# RESILIANT-Z Session 14 — Bounded Policy Proposal and Paired Replay

## Goal

Verify that a Session 13 proposal maps to a predeclared allowlisted parameter, remains inside policy bounds, and can be evaluated using already-produced, paired replay outcomes. No live controller or simulator is invoked by this module.

## Required trust checks

- Read the exact `PolicyProposal` and append-only Session 13 knowledge ledger.
- Verify the knowledge ID, current lifecycle state, independent validation status, source hashes, policy-config hash, operational backend/evidence allowlists, calibrated input conditions, and validated scenario diversity.
- Require proposal status `approval_required`, `automatic_application_allowed=false`, `applied=false`, a known parameter, finite values, permitted bounds and the exact predeclared rule step.
- Candidate replay analysis requires the explicit CLI flag `--allow-candidate-replay-analysis`. This flag does not authorize live policy application.
- Reject duplicate pair IDs, seeds or run IDs. Baseline and candidate must use the same seed, backend, scenario, initial-state ID, task-pattern ID, workload-pattern ID, and parameter keys. Only the declared target parameter may differ, and it must match the proposal values.

## Paired replay statistics

The analyzer consumes JSONL that represents already-produced replay runs; it does not launch those runs. It uses the `replay` split only. Pairs outside the validated scenario/condition envelope or with missing/stale/invalid primary measurements are excluded and remain in the audit trail. Measured zero is valid; unmeasured values are never converted to zero.

The primary effect is candidate-minus-baseline, transformed to improvement-positive direction according to `primary_metric_direction`. A two-sided 95% paired Student-t interval is used, with tabulated critical values through 30 degrees of freedom and a normal approximation above 30. A candidate benefit is observed only if the minimum pair count is met, the interval is fully above zero, and the predeclared practical-improvement threshold is reached. This is a descriptive paired replay comparison, not universal causal proof.

Guardrails (example: deadlock events and collision count) are evaluated only when both sides have measured values and matching units. Any regression blocks review; any required unmeasured guardrail blocks operational review. The example discrete-event backend correctly labels physics-based collision/contact and deadlock metrics as unmeasured.

## Hard safety boundary

- The module writes an evidence report only. `live_policy_modified=false`, `automatic_application_allowed=false`, and `human_approval_required=true` are invariants.
- Even when the report says `eligible_for_human_review_not_applied`, this is not an instruction to deploy; it only means the required checks for later human review were met.
- The supplied replay JSONL is a synthetic fixture, not measured physical, Isaac Sim or real-fleet evidence. Session 13's example knowledge records are deliberately blocked, so the smoke test must return a blocked report.
- No controller, robot, simulator, network endpoint, model-provider API or cloud job is contacted.

## Offline command

```bash
.venv/bin/python -m resiliant_z.policy_replay \
  --session14-config configs/policy-replay/session14_config.v1.json \
  --policy-config configs/knowledge/session13_policy_boundaries.v1.json \
  --ledger artifacts/knowledge/knowledge-ledger.v1.jsonl \
  --proposal artifacts/knowledge/policy-proposal.v1.json \
  --replay-pairs configs/policy-replay/session14_replay_pairs.v1.jsonl \
  --output artifacts/policy-replay/session14-report.v1.json
```

To analyze a previously approved candidate offline, add `--allow-candidate-replay-analysis`; this still does not execute or apply a live policy. A different existing report is never overwritten.

## Acceptance

- bounds, proposal/hash provenance and lifecycle states are fail-closed;
- paired seed/context identity and single-parameter delta are checked;
- positive, regressing, insufficient and unmeasured cases are tested;
- missing/stale data and unmeasured guardrails never become zero;
- report write is no-clobber and replay summary is deterministic for identical inputs;
- full regression, Ruff, format, compile, JSON/JSONL, offline smoke, whitespace and artifact-hash checks all pass.
