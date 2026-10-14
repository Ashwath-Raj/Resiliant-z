import json

from resiliant_z.pipeline import run_demo


def test_demo_writes_artifacts_and_labels_surrogate_honestly(tmp_path):
    summary = run_demo(
        output_dir=tmp_path,
        hypotheses_mode="local",
        seeds_per_cell=3,
        replay_seeds=3,
    )
    assert summary["backend"] == "surrogate"
    assert "NOT ISAAC SIM" in summary["evidence_label"]
    assert summary["discovery"]["status"] == "validated"
    assert summary["counts"]["discovery_runs"] == 12
    assert summary["counts"]["validation_runs"] == 12
    assert summary["counts"]["replay_runs"] == 6
    assert (tmp_path / "runs.jsonl").is_file()
    assert (tmp_path / "manifests.jsonl").is_file()
    assert "SURROGATE" in (tmp_path / "report.md").read_text()
    data = json.loads((tmp_path / "summary.json").read_text())
    assert data["hypothesis_generation"]["source"] == "local_baseline"
