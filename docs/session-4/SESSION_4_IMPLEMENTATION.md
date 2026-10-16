# RESILIANT-Z Phase I — Session 4: Baseline Predictions and Residuals

## Scope

This session adds a transparent, backend-independent baseline profile and residual calculator. It does **not** implement model/reality-gap alerts, causal conclusions, hypothesis generation, or policy changes; those remain later-session work.

## Method

- Fit a per-metric arithmetic mean from telemetry windows sharing one `scenario_id` and one `backend_id`.
- Require at least two distinct training runs and, by default, at least three measured observations for each included metric.
- Exclude values whose quality is anything other than `measured`. A measured numeric zero remains valid evidence.
- Exclude metrics with inconsistent units or insufficient coverage and record the reason in `excluded_metrics`.
- Predict a held-out window using each metric's training mean.
- Residual convention: `observed - predicted`. Positive means the observed value exceeds the baseline.
- Standardized residual is `(observed - predicted) / training sample standard deviation`; it is `null` for zero variance rather than infinity.
- Reject evaluation on a training run ID to avoid direct holdout leakage. Reject scenario/backend mismatches and unit mismatches.

## Limitations

This is a constant mean baseline, not a scenario-conditioned regression model. It will not identify the cause of a deviation and does not declare an anomaly. Sampling windows from a run may be autocorrelated; standardization is descriptive, not a calibrated significance test. The profile must be trained separately for each scenario/backend cohort and evaluated against held-out runs.

## Files

- `src/resiliant_z/baseline.py` — immutable Pydantic contracts and fit/evaluate functions.
- `tests/test_session4_baseline.py` — tests for fit, residual sign, data quality, units, cohort boundaries, holdout leakage, zero variance, and serialization.
- `configs/baseline/session4_fixture.v1.jsonl` — synthetic-only example; not physical calibration data.

## Acceptance gate

Session 4 is acceptable only if the target repository passes the new test module, full regression tests, Ruff lint, Ruff format check, Python compilation and `git diff --check`. Verify the printed results from the actual repository. Do not proceed to Session 5 until reviewed.
