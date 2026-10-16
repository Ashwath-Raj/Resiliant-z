# RESILIANT-Z Session 7 — Semantic Experiment Compiler

## Purpose

Convert one already-schema-shaped, provisional hypothesis into a deterministic and bounded experiment DSL/manifest. The compiler is a trust boundary: it accepts only registered scenario IDs, factors, policy parameters, value types, registered levels, metrics, and local backends. It does not execute the output.

## Version 1 design

- Design: paired single-factor (`control` vs `treatment`). Only the hypothesis focus variable is changed; every other registered factor and policy value is held constant.
- Control level: the nearest distinct registered level (ties use the lower numeric value for determinism).
- Treatment: the hypothesis's registered focus value.
- Scenario factor levels must be declared `test_levels`; policy values must be a registered `candidate_values` entry or the parameter's `default_value`.
- The trusted compiler config controls scenario IDs, backends, target metrics, value types, horizon, replicas, maximum run count, manifest size and the list of known interactions.
- Interaction terms are not supported by compiler version 1. Even a listed term is rejected with `design_not_implemented` until a specific interaction design has been implemented.
- Run seeds and run-state transitions are deferred to Session 8. `run_count` is the proposed pair-arm count, not proof that runs happened.

## Files

- `src/resiliant_z/experiment_compiler.py`: strict models, registry construction, compiler, atomic output writer and offline CLI.
- `tests/test_session7_experiment_compiler.py`: allowlisted compilation and rejection paths.
- `configs/experiment-compiler/session7_config.v1.json`: local allowlists and hard bounds.
- `configs/experiment-compiler/session7_hypothesis.v1.json`: synthetic example input only.
- `docs/session-7/schemas/`: versioned compiler config and manifest schemas.

## Run the example

From the project root, after Session 7 is installed:

```bash
.venv/bin/python -m resiliant_z.experiment_compiler \
  --hypothesis configs/experiment-compiler/session7_hypothesis.v1.json \
  --scenario configs/warehouse_scenario.example.v1.json \
  --config configs/experiment-compiler/session7_config.v1.json \
  --output artifacts/session7/compiled-manifest.json
```

This writes a manifest only. It does not invoke a simulator, shell command, network provider, cloud job or model endpoint. The CLI permits only `discrete_event` and `surrogate` backends. The example scenario and values are synthetic and uncalibrated.

## Error codes

Common rejection codes include `hypothesis_too_large`, `malformed_json`, `invalid_hypothesis_schema`, `unsupported_scenario`, `scenario_mismatch`, `unsupported_backend`, `unregistered_metric`, `factor_registry_mismatch`, `policy_registry_mismatch`, `factor_value_out_of_range`, `factor_value_out_of_registry`, `policy_value_out_of_range`, `policy_value_out_of_registry`, `unregistered_focus_variable`, `no_control_level`, `horizon_limit_exceeded`, `replicate_limit_exceeded`, `run_limit_exceeded`, `unsupported_interaction`, and `design_not_implemented`.

## Session 7 acceptance

- Valid allowlisted hypothesis produces a deterministic, self-validating manifest.
- Unknown parameter, invalid range/value, unsupported scenario/backend/metric, malformed JSON, oversized request and interactions are rejected.
- Control and treatment differ only in the declared focus variable.
- No arbitrary code/commands are accepted or executed.
- Manifest IDs are based on canonical content; source hypothesis/scenario/config SHA-256 hashes are included.
- Seed allocation and execution remain explicitly disabled/deferred.

## Limits

This is a semantic compiler prototype, not an experimental result. It does not select seeds, dispatch jobs, execute a simulation, establish causal effects or authorize a policy. Those concerns belong to later sessions, and independent candidate validation is deferred to Phase III.
