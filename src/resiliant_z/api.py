"""Local API and browser dashboard for the first benchmark."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from resiliant_z import __version__
from resiliant_z.llm.nebius import NebiusConfigurationError, NebiusRequestError
from resiliant_z.pipeline import run_demo

STATIC_DIR = Path(__file__).parent / "static"
app = FastAPI(
    title="RESILIANT-Z",
    description="Evidence-driven operational discovery for simulated multi-robot fleets.",
    version=__version__,
)


class DemoRequest(BaseModel):
    hypotheses_mode: Literal["local", "auto", "nebius"] = "local"
    seeds_per_cell: int = Field(default=5, ge=3, le=20)
    replay_seeds: int = Field(default=12, ge=3, le=50)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "project": "RESILIANT-Z", "version": __version__}


@app.post("/api/demo")
def demo(request: DemoRequest) -> dict:
    try:
        return run_demo(
            output_dir="artifacts/web-demo",
            hypotheses_mode=request.hypotheses_mode,
            seeds_per_cell=request.seeds_per_cell,
            replay_seeds=request.replay_seeds,
        )
    except NebiusConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NebiusRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
