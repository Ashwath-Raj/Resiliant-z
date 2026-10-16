# RESILIANT-Z Session 5 — Persistent Model/Reality-Gap Detector

## Scope

This session adds a deterministic gap detector that consumes held-out `BaselineEvaluation` objects from Session 4. It does not fit baselines, infer causes, generate experiments, update policies, run a simulator, call an LLM, or claim physical validation.

## Detection contract

For each configured metric, a window breaches a threshold when either:

- `abs(residual) >= absolute_residual_threshold`, where the threshold uses the metric's baseline unit; or
- `standardized_residual_threshold` is configured, the standardised residual exists, and its absolute value meets/exceeds that threshold.

A candidate becomes an active gap only after the configured number of **contiguous, measured breach windows**. A configured number of contiguous, measured below-threshold windows is required to clear an active gap. The event log records candidates, openings, persistence, clear-pending windows, closures, normal windows, insufficient evidence and rejected out-of-order windows.

## Data and safety rules

- Observed-minus-predicted residuals come from Session 4 `BaselineEvaluation`; the detector does not recalculate predictions.
- A measured numeric zero is a real observation. Missing, stale, not-applicable, or not-measured observations are not zero and do not count as recovery.
- An unmeasured window breaks the consecutive evidence streak. If a gap is already open, it stays open until the required measured clear windows arrive.
- Only exact contiguous windows count toward a persistence streak. A time gap resets that streak; overlapping/duplicate/older windows return `out_of_order` and do not alter the series state.
- Series state is partitioned by baseline, scenario, backend and metric. This prevents a baseline or backend switch from silently inheriting another series' evidence.
- State and a bounded event history are stored in a versioned JSON file using an atomic replace. The configuration fingerprint prevents silently reopening state with changed thresholds. The state file is single-writer; concurrent processes need external coordination before production use.
- The detector is evidence bookkeeping, not causal inference, a safety proof, or authorization to change a robot policy.

## Example

The example configuration flags `queue_length` with an absolute residual threshold of 3 tasks, an optional standardized threshold of 1.5, two contiguous measured breach windows to open, and two contiguous measured clear windows to close. Example values are synthetic and deliberately illustrative; they are not calibrated warehouse limits.

A minimal integration looks like:

```python
from datetime import datetime, timezone
from resiliant_z.gap_detector import GapDetector, GapDetectorConfig

config = GapDetectorConfig.model_validate_json(
    open("configs/gap-detector/session5_config.v1.json", encoding="utf-8").read()
)
detector = GapDetector(config, "artifacts/gap-detector/state.v1.json")
assessments = detector.ingest(
    held_out_baseline_evaluation,
    window_start=datetime.fromisoformat("2026-10-16T08:00:00+00:00"),
    window_end=datetime.fromisoformat("2026-10-16T08:01:00+00:00"),
)
```

The fixture JSONL shows the record envelope (`window_start`, `window_end`, and a serialized Session 4 evaluation) but is not an automatic production feed. Session 6 will handle hypothesis generation; do not advance until this session's complete validation is green and reviewed.

## Acceptance checks

1. One breach produces a candidate when two contiguous windows are required; the second contiguous breach opens the gap.
2. A required clear streak closes an active gap; one clear window does not.
3. Missing/stale values neither become zero nor clear a gap.
4. Out-of-order/overlapping windows are rejected without mutating that metric's state.
5. A skipped time interval restarts the consecutive-evidence count.
6. State and event history survive process restart and configuration changes fail closed.
7. Focused tests, full project tests, Ruff, formatting, compilation, schema/fixture JSON and whitespace checks pass.
