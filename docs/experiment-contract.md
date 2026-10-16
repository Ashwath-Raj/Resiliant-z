# Experiment manifest and result contract

## Manifest

Every run is defined by an `ExperimentManifest` containing:

- contract `schema_version` (`1.0`)
- unique `experiment_id`
- `scenario_id`, with optional explicit scenario version and SHA-256 configuration hash
- `stage`: discovery, validation, policy_selection, or replay
- deterministic random `seed`
- bounded parameters (`traffic_demand`, `priority_ratio`, `bypass_ratio`)
- source Git SHA (`git_sha`)

Inputs are validated before execution. Unknown fields, out-of-range values and malformed IDs are rejected by Pydantic.

## Run result

`SimulationRun` carries its own `schema_version`, run ID, manifest, backend and optional backend version, start/end timestamps, status, notes, failure reason and log reference. Its provenance records the code SHA and scenario configuration hash and is derived from legacy manifest fields when reading older result payloads.

Statuses distinguish `completed`, `failed`, `timeout`, `incomplete` and `invalidated`. A completed run requires throughput, wait, queue-growth and occupancy values. Incomplete/failed records may retain null metric values and a failure reason rather than fabricated measurements.

`deadlock_events` is nullable. A backend without an implemented detector reports it as `null`/unmeasured; zero is reserved for a measured count. The exact unit and aggregation window must be documented in the simulator adapter. Do not mix metrics from different scenario versions without marking the difference.

## Reproducibility and provenance

For each run, preserve the manifest, seed, simulator backend/version, scenario version/configuration hash, metrics, Git SHA and execution logs. Existing payloads without new version/provenance fields remain readable with compatibility defaults. A real Isaac Sim result should additionally record the Isaac Sim image/release, GPU host identifier (non-secret), driver, start/end time and scene asset hashes.

The CSV importer validates the existing required columns and accepts optional version, timestamp and failure columns. Blank/`null`/`unmeasured` deadlock values stay null; it does not attest that data is authentic, and provenance must be checked against host-side logs.
