import csv
import json
import re

import pytest

from resiliant_z.stress_test import _make_manifests, run_fleet_stress_test


def test_manifest_grid_is_paired_and_complete():
    ms = _make_manifests(
        demands=(0.55, 0.8),
        priorities=(0.15, 0.3),
        seeds=(101, 102, 103),
        bypass_ratio=0.45,
        detour_cost_seconds=2.5,
    )
    assert len(ms) == 36
    assert len({m.experiment_id for m in ms}) == len(ms)
    for d in (0.55, 0.8):
        for p in (0.15, 0.3):
            for seed in (101, 102, 103):
                cell = [
                    m
                    for m in ms
                    if m.parameters.traffic_demand == d
                    and m.parameters.priority_ratio == p
                    and m.seed == seed
                ]
                assert {m.experiment_id.split("-")[3].lower() for m in cell} == {
                    "baseline",
                    "static",
                    "conditioned",
                }


def test_small_run_writes_all_artifacts(tmp_path):
    s = run_fleet_stress_test(
        tmp_path,
        replay_seeds=3,
        first_seed=900,
        traffic_demand_levels=(0.55, 1.05),
        priority_ratio_levels=(0.15, 0.5),
    )
    assert s["counts"]["total_runs"] == 36
    assert s["counts"]["workload_cells"] == 4
    for name in ("summary.json", "runs.jsonl", "manifests.jsonl", "stress_test.csv", "report.md"):
        assert (tmp_path / name).is_file()
    assert json.loads((tmp_path / "summary.json").read_text())["evidence_label"].endswith(
        "NOT ISAAC SIM"
    )
    with (tmp_path / "stress_test.csv").open(newline="") as f:
        assert len(list(csv.DictReader(f))) == 12


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"replay_seeds": 2}, "at least three"),
        ({"traffic_demand_levels": (0.39,)}, "within [0.4, 1.2]"),
        ({"priority_ratio_levels": (0.7,)}, "within [0.1, 0.6]"),
        ({"bypass_ratio": 0.6}, "within [0.0, 0.5]"),
        ({"detour_cost_seconds": 31}, "within [0.0, 30.0]"),
        ({"traffic_demand_levels": ()}, "non-empty and unique"),
        ({"priority_ratio_levels": (0.15, 0.15)}, "non-empty and unique"),
    ],
)
def test_validation(kwargs, message, tmp_path):
    with pytest.raises(ValueError, match=re.escape(message)):
        run_fleet_stress_test(tmp_path, **kwargs)
