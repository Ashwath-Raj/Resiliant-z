# Session 15 — Final Hardening and Isaac Sim Handoff

## Purpose

Session 15 closes Phase III with an offline repository audit and a versioned handoff contract. It checks that expected software files exist, parses JSON/JSONL under `configs/` and `docs/`, records file hashes, and generates a handoff manifest. It does not claim that Isaac Sim is installed or available.

## Important status distinctions

- `pass_for_handoff_review` means repository structure and scanned JSON/JSONL syntax passed. It is not a production-release certification.
- `software_contracts_prepared_host_not_assessed` means an adapter contract is prepared but the host has not been attested.
- The adapter status is permanently `contract_only_not_implemented` in this session. It is not a functioning Isaac Sim adapter.
- Host details come from operator attestation. The tool does not measure hardware or verify OS/driver compatibility independently.
- An attested host that meets configured numeric thresholds is not automatically authorized to launch a simulator.
- Runtime launch, cloud jobs, live policy mutation and automatic execution are explicitly false in emitted records.

## Running the offline audit

The installer runs the offline audit with output directed to a backup directory outside the repository. You may also run it manually after installation:

```bash
.venv/bin/python -m resiliant_z.release_readiness \
  --project-root "$PWD" \
  --config configs/release-readiness/session15_config.v1.json \
  --output-dir /tmp/resiliant-z-session15-audit
```

The output directory receives `release-audit.v1.json` and `isaac-handoff-manifest.v1.json`. Keep both with the release-review notes. Hashes bind the manifest to the source report and record hashes for required files.

## Adapter contract boundary

The contract lists required capabilities: deterministic seed control, scenario reset, timestamped metrics, run-metadata export and clean shutdown. It specifies schema-version slots. It does not import NVIDIA libraries, download assets, start Isaac Sim, connect to Nebius, or declare any capability as implemented.

## Host checklist

1. Choose the exact Isaac Sim release.
2. Review its official OS, driver, GPU, RAM, storage, and container/runtime requirements.
3. Record operator-attested host details and confirmations in `HostReadinessAttestation`.
4. Review asset sources, permissions, licenses, checksums, and disk requirements.
5. Have a human reviewer authorize a separate smoke test after software contracts and host requirements are reviewed.

`session15_host_requirements.template.json` is an example, not authoritative vendor guidance. Its placeholder release must be replaced and the numeric thresholds verified against the chosen release before constructing `HostReadinessRequirements`.

## Acceptance criteria

- Core files for Sessions 1–14 must be present; the audit configuration cannot remove the built-in required paths.
- All JSON and JSONL files under configured `configs/` and `docs/` paths must parse within the configured file-size limit.
- Missing files, malformed JSON/JSONL and unsafe configured paths block the software gate.
- The handoff never authorizes execution or mutates live policy.
- Tests, Ruff lint/format checks, compilation, JSON validation, `git diff --check`, and baseline artifact checksums pass on the target repository.

## Limitations

This is an offline structure/syntax audit, not a security audit or a runtime verification of all contracts. It does not run tests itself inside the audit function; the installer runs the project test suite separately. It does not verify that listed code implements intended scientific semantics. Any real hardware readiness claims must be independently checked before a host smoke test.
