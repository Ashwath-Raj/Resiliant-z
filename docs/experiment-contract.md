# Experiment manifest and result contract

## Manifest

Every run is defined by an `ExperimentManifest` containing:

- unique `experiment_id`
- versioned `scenario_id`
- `stage`: discovery, validation, or replay
- deterministic random `seed`
- bounded parameters (`traffic_demand`, `priority_ratio`, `bypass_ratio`)
- source Git SHA

Inputs are validated before execution. Unknown fields, out-of-range values and malformed IDs are rejected by Pydantic.

## Result metrics

Every successful simulator run must provide:

- throughput (tasks/minute)
- average wait (seconds)
- queue growth (units/minute in the simulator's defined unit)
- junction occupancy (fraction between zero and one)
- deadlock event count

The exact unit and aggregation window must be documented in the simulator adapter. Do not mix metrics from different scenario versions without marking the difference.

## Reproducibility and provenance

For each run, preserve manifest, seed, simulator backend/version, scenario version, metrics, Git SHA and execution logs. A real Isaac Sim result should additionally record the Isaac Sim image/release, GPU host identifier (non-secret), driver, start/end time and scene asset hashes.

The CSV importer validates a required subset of this contract. It does not attest that data is authentic; provenance must be checked against host-side logs.
