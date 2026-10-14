# Architecture and authority boundaries

## Intended end-to-end loop

```text
fleet telemetry
  -> detect persistent gap
  -> Nemotron proposes competing hypotheses
  -> validate hypothesis schema and allowed factors
  -> generate bounded manifests
  -> execute counterfactual simulations
  -> analyze metrics independently of the LLM
  -> validate on held-out runs
  -> store a provenance-linked discovery
  -> request/use a bounded policy intervention
  -> replay matched conditions
```

## Components in this starter

- `models.py`: strict Pydantic contracts for manifests, metrics, hypotheses and decisions.
- `simulation/surrogate.py`: seeded synthetic queue/congestion benchmark used for local development and CI.
- `experiments/planner.py`: deterministic 2×2 factorial experiment and paired replay plan.
- `llm/nebius.py`: optional Token Factory chat-completions adapter plus explicit local fallback hypotheses.
- `evidence/analyzer.py`: compares a model containing two main effects against a model including their interaction.
- `pipeline.py`: runs the experiment/validation/replay sequence and writes provenance artifacts.
- `simulation/isaac_csv.py`: validates metric exports produced by a separate simulator host runner.
- `api.py` and `static/index.html`: local API and dashboard.

## Authority model

Nemotron output is untrusted data. It is parsed into a strict schema; only declared factors are accepted. A hypothesis is not a discovery. The model's prose never determines the evidence status. Numerical analysis and held-out prediction determine the current benchmark decision.

The initial experiment grid is preregistered. Therefore, the current starter tests the measurement and validation loop; it does not yet show an LLM adaptively selecting experiments. This must be improved before claiming that autonomous experiment selection has been demonstrated.

## Simulator independence

The rest of the pipeline accepts `ExperimentManifest` and `SimulationRun` contracts, independent of simulator APIs. The surrogate implements the runtime protocol. The Isaac Sim host integration should emit the same schema, then the UI/analysis remains unchanged.

## Current limitations

- Surrogate dynamics are synthetic and contain a planted interaction.
- Factor level boundaries are experimental design choices, not discovered thresholds.
- Held-out seeds do not validate transfer to new warehouse layouts.
- The Isaac Sim scene runner and automatic job dispatch are not yet implemented.
- Policy replay is only a synthetic intervention.
