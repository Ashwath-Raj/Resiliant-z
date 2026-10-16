# Session 9 — Optional orchestration boundary

## Purpose

Coordinate each immutable Session 8 `PlannedRun` through the run registry, invoke only a trusted executor adapter, and persist a provenance-bearing JSONL receipt. This layer is an orchestration boundary; a receipt saying `succeeded` means an executor reported completion, **not** that the result is complete, statistically valid, or accepted as evidence. Session 10 performs those checks.

## Safety defaults

- The CLI is preflight-only and performs no execution, simulator calls, networking, or cloud submission.
- Programmatic execution requires both `allow_execution: true` in a trusted config and `explicit_execution_opt_in=True` at the call site.
- The default config allows only `local`; remote execution is disabled.
- There is no concrete Nebius SDK/client or remote submission implementation in this package. `NebiusJobsClient` is a narrow optional interface only. No endpoint was verified or called; do not set remote flags unless a separately reviewed client, credentials/quota checks, image digest, spending controls, and user authorization exist.
- The local adapter accepts a trusted Python callable, not shell text or model-generated code. That callable is responsible for invoking an approved backend and persisting the result payload before returning its location and SHA-256.
- Failure diagnostics persist the exception type rather than arbitrary exception text, which might contain secrets.

## Lifecycle

For each planned run, the orchestrator advances `planned → validated → queued → running → terminal`. Terminal states are `succeeded`, `failed`, `timed_out`, and `incomplete`; an existing invalidated or terminal run is never automatically re-executed. A receipt is appended and fsynced before the registry is moved to the terminal state. If a process restarts with a `running` entry but no durable receipt, that run is marked `incomplete` rather than run again implicitly. Replayed receipts are checked against run/plan/request identity.

## Artifacts

`ExecutionReceipt` records run and plan IDs, canonical request hash, executor kind, status, start/end timestamps, result location/hash, logs location, optional remote job ID/image digest, and a bounded failure reason. `ReceiptJournal` is JSONL, append-only in this module, size-limited, and written with restrictive file permissions.

## Trusted local integration

Construct a `LocalExecutor` with a code-reviewed callback. The callback receives a typed `ExecutionRequest`; convert its `PlannedRun` through the existing, explicit manifest adapter, call the selected local backend through `run_with_backend`, persist the validated backend output, and return an `ExecutorOutcome` with the result location and content hash. The generic interface intentionally does not guess mappings between the new planning DSL and legacy `ExperimentManifest` fields.

## Validation boundary

- Fake local executors test the success/failure/timeout lifecycle without running a simulator.
- Preflight tests demonstrate zero executor calls by default.
- Remote execution stays disabled; no real jobs, credentials, APIs, or network calls are used.
- Evidence acceptance, metric range checks, paired deltas and confidence intervals remain Session 10 responsibilities.
