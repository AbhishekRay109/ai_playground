"""Evaluation metrics.

Deterministic metrics (retrieval hit rate, recall@k, citation validity, tool-selection
success) are computed from the real execution trace. Answer completeness and groundedness
are *lexical estimates* (keyword and token overlap), not judgments of truth, and are labelled
as estimates everywhere they are shown.
"""

from __future__ import annotations

import re
import statistics
from typing import Any

from app.services.embedding_service import tokenize


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def chunk_texts_from_response(resp: dict[str, Any]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for step in resp.get("steps", []):
        if step.get("name") == "document_retrieval" and step.get("status") == "success":
            chunks.extend(step.get("details", {}).get("chunks", []))
    return chunks


def evidence_corpus(resp: dict[str, Any]) -> str:
    parts: list[str] = []
    for step in resp.get("steps", []):
        d = step.get("details") or {}
        parts += [c.get("text", "") for c in d.get("chunks", [])]
        parts += [r.get("snippet", "") for r in d.get("results", [])]
        if d.get("rows"):
            parts.append(" ".join(" ".join(map(str, r)) for r in d["rows"]))
        if d.get("result") is not None:
            parts.append(f"{d.get('expression', '')} = {d['result']}")
    parts += [s.get("excerpt", "") for s in resp.get("sources", [])]
    return "\n".join(parts)


def retrieval_hit(resp: dict[str, Any], phrases: list[str]) -> bool | None:
    if not phrases:
        return None
    texts = [_norm(c.get("text", "")) for c in chunk_texts_from_response(resp)]
    return any(_norm(p) in t for p in phrases for t in texts)


def recall_at_k(resp: dict[str, Any], relevant_chunk_ids: set[str]) -> float | None:
    if not relevant_chunk_ids:
        return None
    retrieved = {c.get("chunk_id") for c in chunk_texts_from_response(resp)}
    return len(retrieved & relevant_chunk_ids) / len(relevant_chunk_ids)


def citation_validity(resp: dict[str, Any]) -> float | None:
    c = resp.get("citations") or {}
    total = c.get("total_markers", 0)
    return None if total == 0 else c.get("valid_markers", 0) / total


def completeness_estimate(answer: str, keywords: list[str]) -> float | None:
    if not keywords:
        return None
    a = _norm(answer).replace(",", "")
    return sum(1 for k in keywords if _norm(k).replace(",", "") in a) / len(keywords)


def groundedness_estimate(answer: str, evidence: str) -> float | None:
    """Share of answer sentences whose content words mostly (≥60%) appear in the evidence."""
    ev_tokens = set(tokenize(evidence))
    if not ev_tokens:
        return None
    body = answer.split("Inference:")[0]
    sentences = [s for s in re.split(r"(?<=[.!?])\s+|\n+", body) if len(tokenize(s)) >= 3]
    if not sentences:
        return None
    supported = 0
    for s in sentences:
        toks = [t for t in tokenize(re.sub(r"\[\d+\]", "", s)) if len(t) > 2]
        if toks and sum(t in ev_tokens for t in toks) / len(toks) >= 0.6:
            supported += 1
    return supported / len(sentences)


_ABSTAIN_MARKERS = (
    "could not find enough information",
    "do not contain enough information",
    "does not contain",
    "not enough information",
    "no information",
)


def abstained(answer: str) -> bool:
    """Whether the answer says the evidence is insufficient (for unanswerable questions)."""
    a = _norm(answer)
    return any(marker in a for marker in _ABSTAIN_MARKERS)


def tool_selection_success(
    resp: dict[str, Any], expected: list[str] | None, forbidden: list[str] | None
) -> bool | None:
    if expected is None and forbidden is None:
        return None
    executed = set(resp.get("executed_tools", []))
    return set(expected or []) <= executed and not (executed & set(forbidden or []))


def summarize(values: list[float | bool | None]) -> float | None:
    vals = [float(v) for v in values if v is not None]
    return round(statistics.fmean(vals), 3) if vals else None


def percentile(values: list[int], p: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(p / 100 * (len(ordered) - 1))))
    return ordered[idx]
