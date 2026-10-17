"""Evaluation endpoints: side-by-side mode comparison and dataset benchmarks."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import get_container
from app.core.container import Container
from app.evaluation import runner

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


@router.post("/compare", response_model=list[runner.CompareResult])
async def compare(req: runner.CompareRequest, c: Container = Depends(get_container)) -> list[runner.CompareResult]:
    """Run the same question through several modes (sequentially) without saving a session."""
    return await runner.compare(c, req)


@router.get("/datasets")
async def datasets() -> list[dict[str, Any]]:
    return runner.list_datasets()


@router.post("/run")
async def run(req: runner.DatasetRunRequest, c: Container = Depends(get_container)) -> dict[str, Any]:
    """Run a benchmark dataset. Ingests the dataset's fixture documents if needed."""
    report = await runner.run_dataset(c, req)
    report["markdown"] = runner.report_markdown(report)
    return report
