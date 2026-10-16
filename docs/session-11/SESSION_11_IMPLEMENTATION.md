# RESILIANT-Z Session 11 — Deterministic Candidate Discovery

## Purpose

Extract interpretable **provisional** candidate relationships from discovery and selection observations. This module is the first Phase III stage. It does not independently validate a candidate, modify fleet policy, or promote knowledge.

## Model and split discipline

The trusted config predeclares the target scenario/backend/metric/unit, registered factor bounds, candidate specs, minimum observation count and minimum practical contrast. Version 1 supports:

- one-factor coded OLS main effects; and
- a predeclared two-factor coded OLS model with the product term, reporting a difference-in-differences contrast.

Only `discovery` and `selection` rows matching the configured scenario, backend, evidence label, target metric and unit contribute to estimation. Validation and replay records are retained in the audit table but are not used by the fit. A seed may not appear in more than one split. Unknown factors, out-of-range values, duplicate observation/run IDs and split-seed overlap fail closed.

## Effect and uncertainty

Each factor is mapped linearly to [-1, +1] over its observed range. For a main effect, the reported contrast is the fitted high-minus-low response over that full range (twice the coded coefficient). For an interaction, the reported contrast is the difference-in-differences over both observed ranges (four times the product-term coefficient). The standard error is derived from the OLS residual variance and inverse design matrix. The reported 95% interval uses the configured normal critical value (default 1.96); it is explicitly exploratory, not a confirmatory Student-t interval.

A candidate is `shortlisted` only if the interval excludes zero and its absolute contrast meets the configured practical threshold. All candidate lifecycle statuses remain `provisional`, regardless of shortlist. No candidate in this stage is `validated`.

## Provenance and limitations

Reports include config hash, eligible-input hash, deterministic batch/candidate IDs, variable ranges, units, calibration status, model version, referenced evidence IDs, a per-observation inclusion/exclusion audit and method limitations. Candidate IDs are deterministic for the same config and eligible evidence. Reports are written atomically and conflicting existing reports are not overwritten.

The example fixture is synthetic and labeled `LOCAL DISCRETE-EVENT FLEET MODEL — NOT ISAAC SIM`. The included `junction_occupancy` interaction is eligible for analysis only when the supplied observation contains an actual value for that registered factor. `measured_unverified` is not the same as calibrated. Observed ranges are sample descriptions, not safe operating envelopes.

## Offline command

```bash
.venv/bin/python -m resiliant_z.candidate_discovery \
  --config configs/candidate-discovery/session11_config.v1.json \
  --input configs/candidate-discovery/session11_observations.v1.jsonl \
  --output artifacts/session11/candidate-discovery-report.v1.json
```

This reads local JSONL and writes a report only; it starts no experiment, simulator, provider request, network call or cloud job.

## Acceptance

Run the Session 11 focused test, full regression suite, Ruff check/format check, compilation, JSON/JSONL validation, `git diff --check`, and verify existing artifact hashes. Phase III continues only after the local validation output is reviewed. Session 12 is the independent validation stage and must use a disjoint validation split with criteria fixed before looking at results.
