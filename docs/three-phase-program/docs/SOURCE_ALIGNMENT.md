# Source Alignment and Scope Decisions

This three-phase program follows the supplied **RESILIANT Product & Research Proposal** and **RESILIANT Technical Implementation 15-Session Plan** rather than introducing a different project.

| Supplied design requirement | Where it lands in this plan |
|---|---|
| Observe → detect gap → hypothesize → experiment → simulate → analyze → validate → update knowledge → replay | Phase II end-to-end pipeline; Phase III is the future embodied backend boundary |
| LLM is not a robot controller | Architecture trust-boundary matrix; Phase II provider and policy limits |
| Strict schema, parameter whitelist, range checks | Phase II experiment compiler |
| Statistical evidence, not LLM text, determines discoveries | Phase II evidence analyzer and independent validation gate |
| Discovery and validation datasets separated | Phase II planner and exit criteria |
| 20–35 AMR target and warehouse with junctions, task zones and charging region | Phase III scene and scaling specification |
| Priority-demand / junction-congestion interaction | Primary experiment target across phases |
| Nebius for model serving / finite batch experiments | Phase II as optional hard-opt-in only; local CPU is default and tests remain offline |
| Reproducibility: IDs, seeds, scenario, config, code SHA | Phase I contracts and Phase III run package |
| Isaac Sim as the embodied laboratory | Phase III adapter readiness only; no simulator run in this bundle |

## Deliberate scope decisions

1. **One repository, three milestones.** Do not copy source into `phase1/`, `phase2/` and `phase3/`; use branches and acceptance gates. Duplicated engines will drift.
2. **CPU model is a reference, not a twin.** Keep its limitations explicit. Isaac Sim is a later different backend, not merely a renderer for the queueing model.
3. **No shadow-model evidence substitution.** A small independent policy/event scaffold may be useful as a test double, but it must not be described as the canonical RESILIANT engine or Isaac-derived metrics.
4. **Cloud is opt-in.** The proposal maps Nebius to serving and scalable experiments, but credentials, quotas and spend permissions are not established here. No API call occurs by default.
5. **Phase III ends before execution.** Environment preparation, contracts, configs, fake tests and manual checklist are in scope; installation, large downloads, simulator startup and GPU runs are not.
6. **No unverified host assumptions.** Current official Isaac documentation is versioned; the provider's actual release and host capabilities must decide the final dependency and ROS selection.

The JSON Schemas in `schemas/` are **target interchange contracts**, not assertions that the current Pydantic models already expose those exact fields. Phase I must migrate the existing Pydantic models and `isaac_csv.py` importer behind compatibility tests. In particular, `deadlock_events` becomes nullable until the relevant backend measures it, and statuses must distinguish timeout/incomplete/invalidated runs from completed evidence. Do not wire these schemas into production validation until that migration is implemented and reviewed.
