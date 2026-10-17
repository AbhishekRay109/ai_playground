"""Evaluation runner: mode comparison and dataset benchmarks."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.core.container import Container
from app.core.errors import AppError, NotFound
from app.evaluation import metrics as m
from app.schemas.chat import ChatRequest, Mode, RequestSettings, ToolName
from app.services.chat_service import ChatService

DATASETS_DIR = Path(__file__).parent / "datasets"
FIXTURES_DIR = Path(__file__).parent / "fixtures"


class CompareRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    modes: list[Mode] = Field(min_length=1, max_length=5)
    enabled_tools: list[ToolName] = Field(default_factory=lambda: list(ToolName))
    settings: RequestSettings = Field(default_factory=RequestSettings)


class CompareResult(BaseModel):
    mode: Mode
    response: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class DatasetRunRequest(BaseModel):
    dataset: str = Field(default="default", pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    item_ids: list[str] | None = None


def list_datasets() -> list[dict[str, Any]]:
    out = []
    for path in sorted(DATASETS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out.append(
            {
                "name": data["name"],
                "description": data.get("description", ""),
                "items": len(data["items"]),
                "documents": data.get("documents", []),
                "modes": sorted({i["mode"] for i in data["items"]}),
            }
        )
    return out


def load_dataset(name: str) -> dict[str, Any]:
    path = DATASETS_DIR / f"{name}.json"
    if not path.is_file():
        raise NotFound(f"Dataset '{name}' not found.")
    return json.loads(path.read_text(encoding="utf-8"))


async def compare(container: Container, req: CompareRequest) -> list[CompareResult]:
    service = ChatService(container)
    results = []
    for mode in req.modes:
        chat_req = ChatRequest(
            question=req.question,
            mode=mode,
            enabled_tools=req.enabled_tools if mode == Mode.AGENT else [],
            settings=req.settings,
        )
        try:
            resp = await service.execute(chat_req, persist=False)
            results.append(CompareResult(mode=mode, response=resp.model_dump(mode="json")))
        except AppError as exc:
            results.append(CompareResult(mode=mode, error=exc.to_dict()))
    return results


async def _ensure_documents(container: Container, filenames: list[str]) -> dict[str, str]:
    ids: dict[str, str] = {}
    for name in filenames:
        data = (FIXTURES_DIR / name).read_bytes()
        result = await container.documents.ingest(name, data)
        if result.status == "error" or not result.document_id:
            raise AppError(f"Could not ingest evaluation document {name}: {result.error}", code="eval_setup_failed")
        ids[name] = result.document_id
    return ids


async def run_dataset(container: Container, req: DatasetRunRequest) -> dict[str, Any]:
    dataset = load_dataset(req.dataset)
    started = time.perf_counter()
    doc_ids = await _ensure_documents(container, dataset.get("documents", []))
    all_chunks = container.documents_repo.chunks_for_documents(list(doc_ids.values()))
    service = ChatService(container)
    items = [i for i in dataset["items"] if not req.item_ids or i["id"] in req.item_ids]
    rows: list[dict[str, Any]] = []
    for item in items:
        phrases = item.get("evidence_contains", [])
        relevant = {c.id for c in all_chunks if any(m._norm(p) in m._norm(c.text) for p in phrases)}
        chat_req = ChatRequest(
            question=item["question"],
            mode=Mode(item["mode"]),
            enabled_tools=[ToolName(t) for t in item.get("enabled_tools", [])],
            settings=RequestSettings(document_ids=list(doc_ids.values())),
        )
        row: dict[str, Any] = {"id": item["id"], "mode": item["mode"], "question": item["question"]}
        try:
            resp = (await service.execute(chat_req, persist=False)).model_dump(mode="json")
        except AppError as exc:
            row.update({"status": "error", "error": exc.message, "task_completed": False})
            rows.append(row)
            continue
        answer = resp["answer"]
        completeness = m.completeness_estimate(answer, item.get("expected_keywords", []))
        tool_ok = (
            m.tool_selection_success(resp, item.get("expected_tools"), item.get("forbidden_tools"))
            if item["mode"] == "agent"
            else None
        )
        row.update(
            {
                "status": resp["status"],
                "answer": answer,
                "latency_ms": resp["latency_ms"],
                "executed_tools": resp["executed_tools"],
                "sources": len(resp["sources"]),
                "tokens": resp["token_usage"],
                "retrieval_hit": m.retrieval_hit(resp, phrases),
                "recall_at_k": m.recall_at_k(resp, relevant),
                "citation_validity": m.citation_validity(resp),
                "completeness_estimate": completeness,
                "groundedness_estimate": m.groundedness_estimate(answer, m.evidence_corpus(resp)),
                "tool_selection_success": tool_ok,
                "errors": resp["errors"],
            }
        )
        if item.get("expect_insufficient"):
            row["abstained"] = m.abstained(answer)
        row["task_completed"] = (
            row.get("abstained", True)
            and resp["status"] == "success"
            and (completeness is None or completeness >= 0.5)
            and tool_ok is not False
        )
        rows.append(row)

    latencies = [r["latency_ms"] for r in rows if "latency_ms" in r]
    summary = {
        "retrieval_hit_rate": m.summarize([r.get("retrieval_hit") for r in rows]),
        "recall_at_k": m.summarize([r.get("recall_at_k") for r in rows]),
        "citation_validity": m.summarize([r.get("citation_validity") for r in rows]),
        "completeness_estimate": m.summarize([r.get("completeness_estimate") for r in rows]),
        "groundedness_estimate": m.summarize([r.get("groundedness_estimate") for r in rows]),
        "tool_selection_success_rate": m.summarize([r.get("tool_selection_success") for r in rows]),
        "task_completion_rate": m.summarize([r.get("task_completed") for r in rows]),
        "abstention_rate_on_unanswerable": m.summarize([r.get("abstained") for r in rows]),
        "latency_p50_ms": m.percentile(latencies, 50),
        "latency_p95_ms": m.percentile(latencies, 95),
    }
    return {
        "dataset": dataset["name"],
        "run_at": datetime.now(UTC).isoformat(),
        "model": container.runtime.current.chat_model,
        "embedding_model": container.embeddings.model_name,
        "top_k": container.runtime.current.rag_top_k,
        "score_threshold": container.runtime.current.rag_score_threshold,
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "summary": summary,
        "items": rows,
        "notes": [
            "completeness_estimate and groundedness_estimate are lexical heuristics, not judgments of correctness.",
            "recall_at_k counts chunks containing the ground-truth phrase as relevant.",
        ],
    }


def _fmt(v: Any) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def report_markdown(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        f"# Evaluation report: {report['dataset']}",
        "",
        f"- Run at: {report['run_at']}",
        f"- Chat model: `{report['model']}`; embedding model: `{report['embedding_model']}`",
        f"- Retrieval: top_k={report['top_k']}, score_threshold={report['score_threshold']}",
        f"- Duration: {report['duration_ms']} ms",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
    ]
    labels = {
        "retrieval_hit_rate": "Retrieval hit rate",
        "recall_at_k": "Recall@k",
        "citation_validity": "Citation validity",
        "completeness_estimate": "Answer completeness (estimate)",
        "groundedness_estimate": "Groundedness (lexical estimate)",
        "tool_selection_success_rate": "Tool-selection success rate",
        "task_completion_rate": "Task completion rate",
        "abstention_rate_on_unanswerable": "Correct abstention on unanswerable questions",
        "latency_p50_ms": "Latency p50 (ms)",
        "latency_p95_ms": "Latency p95 (ms)",
    }
    lines += [f"| {labels[k]} | {_fmt(v)} |" for k, v in s.items()]
    lines += [
        "",
        "## Items",
        "",
        "| Id | Mode | Status | Tools executed | Hit | Recall@k | Citations | Completeness (est.) | Tool choice | Latency ms |",  # noqa: E501
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in report["items"]:
        lines.append(
            f"| {r['id']} | {r['mode']} | {r['status']} | {', '.join(r.get('executed_tools', [])) or '-'} | "
            f"{_fmt(r.get('retrieval_hit'))} | {_fmt(r.get('recall_at_k'))} | {_fmt(r.get('citation_validity'))} | "
            f"{_fmt(r.get('completeness_estimate'))} | {_fmt(r.get('tool_selection_success'))} | "
            f"{_fmt(r.get('latency_ms'))} |"
        )
    lines += ["", "## Notes", ""] + [f"- {n}" for n in report["notes"]]
    return "\n".join(lines) + "\n"
