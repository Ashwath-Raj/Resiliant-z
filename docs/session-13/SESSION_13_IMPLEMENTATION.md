# RESILIANT-Z Session 13 — Versioned Fleet Knowledge Model

## Objective

Persist Session 12 independently validated findings as versioned, provenance-linked knowledge records. Maintain an append-only lifecycle ledger and produce bounded policy-update proposals without modifying or executing a live fleet policy.

## Input contracts and promotion boundary

Inputs are the exact Session 11 candidate-discovery report, the Session 12 independent-validation report, and a predeclared Session 13 policy-boundary configuration. The validator must confirm that the validation report's `candidate_report_sha256` matches the exact candidate-report bytes, that every result links to an existing candidate and matching `spec_id`, and that a validated result came from a discovery-shortlisted provisional candidate.

A Session 12 result may become `validated_scoped` knowledge only within the tested metric, unit, backend, conditions and scenarios. The candidate remains non-operational by default. Operational policy review requires all of the following: validation status `validated`, an allowlisted operational backend, an exact allowlisted evidence label, all input factor ranges marked `calibrated`, sufficient distinct validation scenarios, and validation evidence links. Session 11/12 local discrete-event fixtures are explicitly labelled synthetic or non-Isaac; their records therefore remain blocked for operational policy review even when their known synthetic contrasts pass the validation test.

## Immutable ledger

`src/resiliant_z/knowledge_model.py` implements:

- versioned knowledge records with observed conditions, effect estimates, confidence intervals, context diversity, evidence IDs, source hashes, and explicit limitations;
- checksummed JSONL entries, appended under a file lock with file mode `0600`;
- idempotent record insertion by deterministic knowledge ID and immutable-content comparison;
- integrity checks, bounded input/ledger size, symlink refusal, duplicate/conflict detection and fail-closed handling of corrupt ledger lines;
- append-only lifecycle events for invalidation and rollback. Record bytes are never rewritten by either operation; effective status is reconstructed from the event history;
- record listing and comparable-effect comparison, with metric/unit mismatches rejected.

The ledger is an application-level append-only file with integrity checks, not a cryptographically signed or tamper-proof archive. Protect it with appropriate filesystem access controls and backups.

## Constrained policy proposal

Policy rules are explicit configuration, not LLM-generated code. Each rule fixes the target metric, required effect sign, allowlisted parameter identifier, direction, step, current reference value, parameter bounds and minimum effect. A proposal is emitted as `approval_required` only when the source knowledge's operational gate is eligible and all rule gates pass. Otherwise a reason-coded blocked proposal is written. All proposals permanently declare `human_approval_required=true`, `automatic_application_allowed=false` and `applied=false`.

The configured current parameter value is a proposal reference value, not a live controller read. This module does not update a controller, assign robots, launch experiments, run a simulator, call an LLM, or connect to the network.

## Commands

Ingest the bundled synthetic Session 12 report into a chosen ledger:

```bash
.venv/bin/python -m resiliant_z.knowledge_model ingest \
  --candidate-report configs/knowledge/session13_candidate_report.fixture.v1.json \
  --validation-report configs/knowledge/session13_validation_report.fixture.v1.json \
  --policy-config configs/knowledge/session13_policy_boundaries.v1.json \
  --ledger artifacts/knowledge/knowledge-ledger.v1.jsonl
```

List records and current lifecycle state:

```bash
.venv/bin/python -m resiliant_z.knowledge_model list \
  --ledger artifacts/knowledge/knowledge-ledger.v1.jsonl
```

Propose (but never apply) a policy change:

```bash
.venv/bin/python -m resiliant_z.knowledge_model propose-policy \
  --ledger artifacts/knowledge/knowledge-ledger.v1.jsonl \
  --knowledge-id know-REPLACE_WITH_A_REAL_ID \
  --policy-config configs/knowledge/session13_policy_boundaries.v1.json \
  --output artifacts/knowledge/policy-proposal.v1.json
```

Invalidate or roll back a record by appending an event:

```bash
.venv/bin/python -m resiliant_z.knowledge_model invalidate \
  --ledger artifacts/knowledge/knowledge-ledger.v1.jsonl \
  --knowledge-id know-REPLACE_WITH_A_REAL_ID \
  --reason 'independent follow-up evidence contradicts this finding'
```

## Synthetic fixture limitation

The bundled Session 12 report yields two `validated_scoped` research records. Their evidence is the local discrete-event synthetic fixture, so both operational gates must remain `blocked`. This demonstrates the distinction between passing a synthetic statistical test and having calibrated, operationally eligible evidence. These fixture records are not real-world or Isaac Sim findings.

## Acceptance

- round-trip serialization and exact source-hash verification;
- no promotion from non-validated, non-shortlisted, or mismatched evidence;
- tamper detection, no-clobber persistence, idempotent inserts, symlink refusal and append-only invalidation/rollback;
- policy proposal bounds, allowlists and human-approval gate;
- synthetic evidence remains operationally blocked;
- focused tests, full regression suite, Ruff, formatting, Python compilation, JSON/JSONL validation, offline CLI smoke, `git diff --check`, and existing artifact checksum preservation pass.
