# RESILIANT-Z Session 12 — Independent Validation

## Goal

Independently validate Session 11's **provisional** candidates using criteria frozen in a trusted Session 12 configuration and held-out observations from the `validation` split. This module must not trust an LLM or the candidate discovery report to choose the validation thresholds.

## Contract and statistics

- Inputs: a Session 11 `provisional_candidates_only` report, a predeclared JSON config, and JSONL observations annotated with `discovery`, `selection`, `validation`, or `replay` split; each observation carries seed, replicate, candidate/spec, scenario, metric/unit, quality, factor levels, initial state, task pattern and workload pattern.
- Training rows are used only to verify links to the candidate's referenced evidence IDs and to establish which seeds/scenarios/context identifiers were already used. They are not used in the validation estimate. Replay rows are audit-only.
- Validation seeds must be disjoint from discovery/selection seeds. Validation scenarios, initial state IDs, task pattern IDs and workload pattern IDs must also be disjoint from the training context. Validation scenarios must come from the predeclared allowlist.
- Main effects use paired high-minus-low contrasts. Interactions use a predeclared difference-in-differences contrast: `high_high - high_low - low_high + low_low`. A replicate must contain every required measured cell, with the same seed, scenario, initial state, task pattern and workload pattern. Unregistered nuisance factors must remain constant across contrast cells.
- Confidence interval: two-sided 95% Student-t interval of the replicate contrasts; exact tabulated critical values are used through 30 degrees of freedom, then a deterministic Cornish-Fisher approximation. Sample standard deviation uses `n-1` in the denominator.
- Outcome is `validated` only when predeclared direction, interval, minimum replicate count, concordance, practical-impact, effect-retention and context-diversity criteria all pass. A clear opposite/too-small/low-concordance effect is `rejected`. Insufficient precision or replicates is `inconclusive`. Broken identity/seed/context/metadata protocol is `invalidated`.
- Missing, stale, unmeasured and not-applicable values are never turned into zero. Incomplete contrast blocks are excluded and retained in the audit. Measured zero remains valid.
- The report hashes the exact config, candidate report and observation bytes; outputs are deterministic for identical input bytes and cannot overwrite a different existing report.

## Important scope limitations

- Candidate validation is still restricted to its declared backend, metric, factor levels and allowed validation scenarios. It does not establish universality or physical/real-world calibration.
- Session 12 emits validation outcomes only. **It does not create, promote or persist a validated knowledge record**; Session 13 owns the versioned knowledge lifecycle.
- The example fixtures are synthetic and use `LOCAL DISCRETE-EVENT FLEET MODEL — NOT ISAAC SIM`. Do not describe those outputs as physical or Isaac Sim evidence.
- Independent validation is not automatically causal inference. Reported contrasts are conditional on the paired design and held-out observations actually supplied.
- No simulation, model-provider request, network call, Nebius job, controller update or policy execution is performed.

## Offline command

```bash
.venv/bin/python -m resiliant_z.independent_validation \
  --config configs/independent-validation/session12_config.v1.json \
  --candidate-report configs/independent-validation/session12_candidate_report.v1.json \
  --observations configs/independent-validation/session12_observations.v1.jsonl \
  --output artifacts/session12/independent-validation-report.v1.json
```

The command writes a report only. Re-running to the same output succeeds only if its bytes match; a conflicting report is preserved and an error is raised.

## Acceptance

Run the Session 12 focused suite, full regression suite, Ruff check/format check, Python compilation, config/fixture/schema JSON validation, CLI smoke test to a temporary backup path, `git diff --check`, and existing-artifact checksum verification. Do not proceed to Session 13 until these checks have passed in the target repository and the resulting outcomes/audit have been reviewed.
