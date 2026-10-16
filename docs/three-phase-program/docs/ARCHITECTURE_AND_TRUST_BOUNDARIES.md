# Architecture and Trust Boundaries

## Desired end-to-end flow

```text
fleet telemetry / controlled scenario
               ↓
      state aggregator + data quality
               ↓
      model/reality-gap detector
               ↓  (persistent gap only)
    Nemotron hypothesis provider
               ↓  untrusted JSON
      schema + factor whitelist
               ↓
      experiment compiler/planner
               ↓  immutable manifests
     local CPU backend by default
          or explicit job adapter
               ↓
     result validation/provenance
               ↓
      deterministic evidence analysis
               ↓
      independent held-out validation
               ↓
     versioned knowledge candidate
               ↓
       policy staging/validation
               ↓
      matched baseline/candidate replay
```

The Phase III backend boundary allows the eventual Isaac Sim executor to emit the same result contract. The pipeline must not assume a simulator exists at import time.

## Authority matrix

| Component | May do | Must not do |
|---|---|---|
| Telemetry/state aggregation | Validate and summarize observed signals | Invent missing metrics or hide stale samples |
| Gap detector | Trigger investigation on a configured rule | Declare a discovered law |
| Nemotron/provider | Suggest competing hypotheses as structured data | Issue robot commands, execute code, set hard limits, approve discovery |
| Experiment compiler | Convert allowed factors to bounded manifests | Accept arbitrary code or unknown parameters |
| Planner/registry | Track runs and separate discovery/validation seeds | Count failed/invalid runs as successes |
| Simulator backend | Execute a validated manifest and report observations | Alter evidence status or fill absent metrics with zero |
| Evidence analyzer | Compute effects, uncertainty and model checks | Use LLM prose to decide significance |
| Validator | Accept/reject/inconclusive based on predeclared tests | Reuse discovery seeds as independent validation |
| Knowledge store | Preserve conditions, provenance and state | Promote unvalidated candidates |
| Policy gate | Select tested, allowlisted parameter changes | Deploy to real robots or execute generated controller code |
| Isaac adapter | Map validated manifests to a physical simulation and export measured data | Drive robots by arbitrary transform edits and call that physics control |

## Core invariants

- All policy arms in a paired comparison use equivalent workload, seed and pre-sampled exogenous randomness wherever the model allows it.
- `run_id`, `experiment_id`, scenario version, seed, source SHA and backend version travel with each result.
- An absent collision detector means collision/deadlock count is unmeasured, not zero.
- The current CPU simulation is the **local discrete-event reference**, not a validated digital twin or Isaac Sim result.
- A new backend is not eligible for evidence promotion until its metrics, failure cases and event instrumentation pass contract tests.
