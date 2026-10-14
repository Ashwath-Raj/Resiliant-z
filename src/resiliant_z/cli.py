"""Command-line interface for RESILIANT-Z."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

from resiliant_z import __version__
from resiliant_z.fleet_pipeline import run_fleet_demo
from resiliant_z.llm.nebius import DEFAULT_BASE_URL, nebius_is_configured
from resiliant_z.pipeline import run_demo
from resiliant_z.simulation.isaac_csv import import_isaac_metrics_csv


def _get_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="resiliant", description="RESILIANT-Z research prototype")
    parser.add_argument("--version", action="version", version=f"RESILIANT-Z {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="run the reproducible local surrogate benchmark")
    demo.add_argument("--output-dir", default="artifacts/demo")
    demo.add_argument("--hypotheses", choices=["auto", "local", "nebius"], default="auto")
    demo.add_argument("--seeds-per-cell", type=int, default=5)
    demo.add_argument("--replay-seeds", type=int, default=12)

    fleet_demo = sub.add_parser(
        "fleet-demo",
        help="run the local CPU discrete-event fleet benchmark (not Isaac Sim)",
    )
    fleet_demo.add_argument("--output-dir", default="artifacts/fleet-demo")
    fleet_demo.add_argument("--seeds-per-cell", type=int, default=5)
    fleet_demo.add_argument("--replay-seeds", type=int, default=12)

    sub.add_parser("doctor", help="check local environment and non-secret configuration state")
    sub.add_parser("models", help="list model IDs visible to your Token Factory API key")
    sub.add_parser("serve", help="start the local dashboard API")
    imported = sub.add_parser("validate-isaac-csv", help="validate a simulator-host metrics CSV contract")
    imported.add_argument("path", help="path to a CSV exported by the Isaac Sim host runner")
    return parser


def _doctor() -> int:
    print(f"RESILIANT-Z {__version__}")
    print(f"Python: {platform.python_version()}")
    print(f"Platform: {platform.platform()}")
    print(f"Nebius Token Factory configured: {'yes' if nebius_is_configured() else 'no'}")
    print(f"Model ID set: {'yes' if os.getenv('NEBIUS_MODEL', '').strip() else 'no'}")
    print("Secret values are intentionally not printed.")
    print("Isaac Sim: not checked or launched by this command; run it on a compatible host.")
    print("Local runtime check passed.")
    return 0


def _models() -> int:
    api_key = os.getenv("NEBIUS_API_KEY", "").strip()
    base_url = os.getenv("NEBIUS_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    if not api_key:
        print("ERROR: NEBIUS_API_KEY is missing. Set it in .env or the shell.", file=sys.stderr)
        return 2
    try:
        response = httpx.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=20,
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        print(f"ERROR: Token Factory model-list request failed: {exc}", file=sys.stderr)
        return 3
    models = body.get("data", [])
    if not isinstance(models, list):
        print("ERROR: Unexpected /models response schema.", file=sys.stderr)
        return 3
    for item in models:
        if isinstance(item, dict) and item.get("id"):
            print(item["id"])
    print(f"\nVisible models: {sum(bool(isinstance(m, dict) and m.get('id')) for m in models)}")
    print("Copy one exact ID into NEBIUS_MODEL in your local .env file.")
    return 0


def main() -> int:
    load_dotenv()
    args = _get_parser().parse_args()
    if args.command == "doctor":
        return _doctor()
    if args.command == "models":
        return _models()
    if args.command == "validate-isaac-csv":
        try:
            runs = import_isaac_metrics_csv(args.path)
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        counts = {}
        for run in runs:
            counts[run.experiment.stage] = counts.get(run.experiment.stage, 0) + 1
        print(json.dumps({"csv": str(Path(args.path).resolve()), "rows_validated": len(runs), "stage_counts": counts, "backend_label": "isaac_sim_import (verify host provenance separately)"}, indent=2))
        return 0
    if args.command == "serve":
        import uvicorn

        host = os.getenv("RESILIANT_HOST", "127.0.0.1")
        port = int(os.getenv("RESILIANT_PORT", "8000"))
        uvicorn.run("resiliant_z.api:app", host=host, port=port, reload=False)
        return 0
    if args.command == "fleet-demo":
        try:
            summary = run_fleet_demo(
                output_dir=Path(args.output_dir),
                seeds_per_cell=args.seeds_per_cell,
                replay_seeds=args.replay_seeds,
            )
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(json.dumps({
            "project": summary["project"],
            "evidence_label": summary["evidence_label"],
            "backend": summary["backend"],
            "runs": summary["counts"],
            "discovery_status": summary["discovery"]["status"],
            "validation_improvement_fraction": summary["discovery"]["validation_improvement_fraction"],
            "policy_replay": summary["policy_replay"],
            "artifacts": str(Path(args.output_dir).resolve()),
        }, indent=2))
        print("\nRead report: " + str((Path(args.output_dir) / "report.md").resolve()))
        return 0 if summary["discovery"]["status"] == "validated" else 2
    if args.command == "demo":
        try:
            summary = run_demo(
                output_dir=Path(args.output_dir),
                hypotheses_mode=args.hypotheses,
                seeds_per_cell=args.seeds_per_cell,
                replay_seeds=args.replay_seeds,
            )
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(json.dumps({
            "project": summary["project"],
            "evidence_label": summary["evidence_label"],
            "runs": summary["counts"],
            "hypothesis_source": summary["hypothesis_generation"]["source"],
            "discovery_status": summary["discovery"]["status"],
            "validation_improvement_fraction": summary["discovery"]["validation_improvement_fraction"],
            "policy_replay": summary["policy_replay"],
            "artifacts": str(Path(args.output_dir).resolve()),
        }, indent=2))
        print("\nRead report: " + str((Path(args.output_dir) / "report.md").resolve()))
        return 0 if summary["discovery"]["status"] == "validated" else 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
