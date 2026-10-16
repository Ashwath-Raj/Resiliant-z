# RESILIANT-Z Session 8 — Experiment Planner and Run Registry

## Scope

Session 8 turns one Session 7 `paired_single_factor` compiled manifest into a deterministic, non-executing run plan. It allocates disjoint discovery, selection, validation, and replay seeds; paired control/treatment runs share the same seed within each split/replicate; and it persists a stateful run registry.

The v1 planner deliberately uses a **predeclared paired single-factor design**. It does not invent new factor values, implement unregistered interactions, execute the backend, make a network call, submit a cloud job, or turn outcomes into validated evidence. Coarse-to-fine searches should be represented by separately reviewed/compiled manifests in a later extension, rather than bypassing the Session 7 registry.

## Files

- `src/resiliant_z/experiment_planner.py` — bounded planner, deterministic seed derivation, plan persistence, run registry, CLI.
- `tests/test_session8_experiment_planner.py` — determinism, disjoint seed sets, paired arms, limits, state transitions, persistence and failure handling.
- `configs/experiment-planner/session8_config.v1.json` — trusted local planning bounds and root seed.
- `configs/experiment-planner/session8_manifest_fixture.v1.json` — synthetic compiled-manifest fixture used for an offline dry demonstration.
- `docs/session-8/schemas/experiment-plan.v1.schema.json` and `run-registry.v1.schema.json` — output schema contracts.

## Seed design

The seed is generated deterministically from the root seed, source manifest ID, split role and replicate index using SHA-256 (`sha256-v1`) and mapped to a non-negative signed 31-bit value. Collision handling is deterministic. Discovery, selection, validation, and replay seed sets are disjoint. Control and treatment within the same split/replicate share one seed to support common random numbers where the backend honors seeded randomness.

A seed being disjoint does not guarantee independence for every backend; backend reproducibility and RNG consumption must be tested separately. Do not tune model or policy parameters on the validation/replay split.

## Run-state machine

`planned → validated → queued → running → succeeded`

Terminal alternatives include `failed`, `timed_out`, `incomplete`, and `invalidated`. Failure/timeout/incomplete/invalidation requires a reason. There is no transition from failure to success; retry under a new plan/run identity instead. A `succeeded` status means the executor says the run completed, **not** that metrics are complete, statistically valid, or admissible as evidence. Session 10 performs result validation and analysis.

## Example command

From the repository root, the default command builds a plan from the synthetic fixture only; it does not run it:

```bash
.venv/bin/python -m resiliant_z.experiment_planner \
  --manifest configs/experiment-planner/session8_manifest_fixture.v1.json \
  --config configs/experiment-planner/session8_config.v1.json \
  --output artifacts/session8/experiment-plan.json \
  --registry artifacts/session8/run-registry.json
```

The sample plans 24 runs (3 paired replicates × 4 seed splits × 2 arms). The command refuses to overwrite a different existing plan file. Choose new output/registry paths to create a new deterministic plan configuration.

## Acceptance criteria

- Same manifest/config yields byte-equivalent typed plan fields and the same plan/run IDs.
- Seed sets are disjoint across the four roles; paired arms share one seed.
- The run count respects both planner and source-manifest caps.
- Each pair differs only on the registered focus variable.
- State transitions are validated and persisted atomically; failed jobs cannot become successful through a state transition.
- Session-focused tests, full repository tests, Ruff lint/format, compilation, JSON syntax and `git diff --check` pass.

## Data labels

The included fixture and example config are synthetic. They are not measured, calibrated warehouse data. A planned run is not simulation output and must not be presented as physical/Isaac Sim evidence.
