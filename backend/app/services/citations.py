"""Citation validation.

The model cites evidence as ``[n]``. After generation, every marker is checked against the
evidence that was actually retrieved in this execution; markers pointing to non-existent
evidence are removed from the answer and reported.
"""

from __future__ import annotations

import re

from app.schemas.chat import CitationReport, Source

# Matches [1], [1, 2], [1][2] (each bracket group handled separately).
_MARKER_RE = re.compile(r"\[(\s*\d{1,3}(?:\s*,\s*\d{1,3})*\s*)\]")


def validate_citations(answer: str, sources: list[Source]) -> tuple[str, CitationReport]:
    valid_ids = {s.id for s in sources}
    total = 0
    valid = 0
    invalid: list[int] = []
    cited: set[int] = set()

    def _replace(match: re.Match[str]) -> str:
        nonlocal total, valid
        nums = [int(n) for n in re.findall(r"\d+", match.group(1))]
        keep = []
        for n in nums:
            total += 1
            if n in valid_ids:
                valid += 1
                keep.append(n)
                cited.add(n)
            else:
                invalid.append(n)
        return "".join(f"[{n}]" for n in keep)

    cleaned = _MARKER_RE.sub(_replace, answer)
    cleaned = re.sub(r"[ \t]+([.,;:])", r"\1", cleaned)
    for s in sources:
        s.cited = s.id in cited
    return cleaned, CitationReport(total_markers=total, valid_markers=valid, invalid_markers=sorted(set(invalid)))


def excerpt(text: str, query: str | None = None, length: int = 280) -> str:
    """A short supporting excerpt; prefers the sentence with the most query-term overlap."""
    text = " ".join(text.split())
    if len(text) <= length:
        return text
    if query:
        terms = {t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 3}
        sentences = re.split(r"(?<=[.!?])\s+", text)
        best_i, best_score = 0, -1
        for i, sent in enumerate(sentences):
            score = len(terms & set(re.findall(r"[a-z0-9]+", sent.lower())))
            if score > best_score:
                best_i, best_score = i, score
        if best_score > 0:
            start = text.find(sentences[best_i])
            snippet = text[start : start + length]
            return ("…" if start > 0 else "") + snippet + ("…" if start + length < len(text) else "")
    return text[:length].rstrip() + "…"
