# RESILIANT-Z Session 10 — Deterministic Evidence Analyzer

## Scope

Session 10 consumes the Session 7 compiled manifest, Session 8 planned runs, Session 9 execution receipts, and the local result artifacts referenced by successful receipts. It writes a deterministic, provisional evidence report. It does not execute runs or promote a hypothesis to validated knowledge.

## Provenance gate

Before a value is analyzed, the analyzer checks:

1. The compiled-manifest ID and canonical SHA-256 match the Session 8 plan.
2. The plan's scenario, backend, and target metric match the manifest.
3. Each receipt references a planned run, the same plan ID, and the request hash computed from that immutable planned run.
4. The result artifact is a local file under the configured result root, stays within the size limit, matches the SHA-256 recorded in its Session 9 receipt, and matches the planned run's ID, scenario hash, backend, split, arm, replicate, seed, and metric.
5. The target observation is explicitly measured, uses the configured unit, and lies inside the trusted metric range.

URI locations and paths escaping `result_root` are not fetched. Session 10 has no network code. Invalid results are excluded with an audit reason; provenance conflicts in the plan/receipt input are fatal errors.

## Primary analysis

- Primary split: `validation` only.
- Pairing key: preallocated `(replicate_index, seed)`.
- Effect: treatment minus control.
- Statistics: mean paired effect, sample standard deviation, Cohen's dz when defined, and two-sided 95% Student-t interval.
- Decision: compare the interval to the direction and predeclared practical-effect threshold from trusted inputs.
- Minimum pairs: configured; fewer pairs always yield `insufficient_pairs`.

The bundled config targets `mean_wait_seconds`, unit `seconds`, allowed range `[0, 3600]`, and requires at least three complete validation pairs. Adjust these bounds only through a reviewed, versioned analysis config before analysis; they are not calibrated universal limits.

The Student-t critical-value table covers degrees of freedom 1 through 24, consistent with a 200-run plan cap and the four independent seed splits. Larger samples fail closed rather than silently switching methods.

## Audit semantics

The report retains one audit entry for every planned run, including `not_executed`, `failed`, `timed_out`, `incomplete`, `invalid_result`, missing/unmeasured metrics, wrong units, out-of-range values, and valid runs from non-validation splits. These rows are not imputed or converted to zero. A valid validation result without a valid counterpart is marked `excluded_unpaired`.

Discovery, selection, and replay records are retained for audit but do not contribute to the primary inferential decision. This reduces data-leakage risk; it does not replace a preregistered scientific review or independent validation.

## Determinism and files

- JSON result artifacts are serialized and atomically created by `save_result_artifact_atomic`; the caller supplies the returned byte hash in the Session 9 success receipt.
- A conflicting pre-existing result artifact/report is not overwritten.
- Report IDs are derived deterministically from the plan, manifest/config hashes, receipts, audit and paired effects. No wall-clock timestamp is inserted into the report.
- The report is always `provisional_evidence_report`; no finding is promoted to validated fleet knowledge.

## Offline command

After a plan, receipts, and local result artifacts exist:

```bash
.venv/bin/python -m resiliant_z.evidence.session10 \
  --manifest configs/experiment-planner/session8_manifest_fixture.v1.json \
  --plan artifacts/session8/experiment-plan.json \
  --receipts artifacts/session9/execution-receipts.jsonl \
  --config configs/evidence/session10_config.v1.json \
  --result-root . \
  --output artifacts/session10/evidence-report.v1.json
```

When receipts are absent, the command can produce an audit-only report with `insufficient_pairs`; it does not launch work. It must never be described as observed performance evidence if the runs were not executed.

## Acceptance

Session 10 requires focused and full tests, Ruff lint/format, Python compilation, JSON/JSONL parsing, `git diff --check`, and unchanged pre-existing artifact hashes. Phase II remains provisional until Sessions 6–10 are reviewed together end-to-end. The eventual Phase II commit/push must wait for that gate and separately repair the already-known staged Markdown trailing whitespace from the earlier failed commit attempt.
