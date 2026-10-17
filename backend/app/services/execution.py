"""Execution recording shared by every mode.

A :class:`RunRecorder` collects steps, sources, token usage and errors for one request and
emits typed events as they happen. A step is reported as finished only after the work it
describes has actually returned.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.schemas.chat import (
    ChatRequest,
    CitationReport,
    Counts,
    ExecutionStep,
    Mode,
    Source,
    StepStatus,
    TokenUsage,
)
from app.services.llm_service import LLMResult

Emit = Callable[[dict[str, Any]], None]


@dataclass
class EffectiveOptions:
    """Runtime settings merged with per-request overrides."""

    model: str
    temperature: float
    max_tokens: int
    timeout_s: float
    top_k: int
    score_threshold: float
    search_results: int
    document_ids: list[str] | None = None


@dataclass
class RunRecorder:
    mode: Mode
    emit: Emit
    available_tools: list[str] = field(default_factory=list)
    steps: list[ExecutionStep] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    selected_tools: list[str] = field(default_factory=list)
    executed_tools: list[str] = field(default_factory=list)
    counts: Counts = field(default_factory=Counts)
    tokens: TokenUsage = field(default_factory=TokenUsage)
    citations: CitationReport = field(default_factory=CitationReport)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    model: str | None = None
    embedding_model: str | None = None
    answer: str = ""
    status: str = "success"
    _started: dict[str, float] = field(default_factory=dict)

    # ---------------------------------------------------------------- steps
    def start_step(
        self, kind: str, name: str, *, purpose: str | None = None, input_summary: str | None = None
    ) -> ExecutionStep:
        step = ExecutionStep(
            id=uuid.uuid4().hex[:12],
            kind=kind,
            name=name,
            status="running",  # type: ignore[arg-type]
            purpose=purpose,
            input_summary=input_summary,
        )
        self.steps.append(step)
        self._started[step.id] = time.perf_counter()
        self.emit({"type": "tool_start", "step": step.model_dump()})
        return step

    def finish_step(
        self, step: ExecutionStep, status: StepStatus, result_summary: str, details: dict[str, Any] | None = None
    ) -> ExecutionStep:
        step.status = status
        step.result_summary = result_summary
        if details:
            step.details.update(details)
        step.latency_ms = int((time.perf_counter() - self._started.pop(step.id, time.perf_counter())) * 1000)
        if step.kind == "tool" and status in ("success", "error", "timeout"):
            # A tool counts as executed once it actually ran, whatever the outcome.
            if step.name not in self.executed_tools:
                self.executed_tools.append(step.name)
            self.counts.tool_calls += 1
        self.emit({"type": "tool_end", "step": step.model_dump()})
        return step

    def record_rejected(self, name: str, purpose: str | None, input_summary: str | None, reason: str) -> None:
        step = ExecutionStep(
            id=uuid.uuid4().hex[:12],
            kind="tool",
            name=name,
            status="rejected",
            purpose=purpose,
            input_summary=input_summary,
            result_summary=reason,
            latency_ms=0,
        )
        self.steps.append(step)
        self.emit({"type": "tool_end", "step": step.model_dump()})

    # ---------------------------------------------------------------- other
    def add_sources(self, sources: list[Source]) -> None:
        self.sources.extend(sources)
        self.emit({"type": "sources", "sources": [s.model_dump() for s in self.sources]})

    def add_llm_usage(self, result: LLMResult) -> None:
        self.model = result.model or self.model
        self.tokens.prompt_tokens += result.prompt_tokens
        self.tokens.completion_tokens += result.completion_tokens
        self.tokens.estimated = self.tokens.estimated or result.estimated_tokens

    def delta(self, text: str) -> None:
        if text:
            self.emit({"type": "delta", "text": text})

    def status_message(self, message: str) -> None:
        self.emit({"type": "status", "message": message})

    def add_error(self, code: str, message: str, step: str | None = None) -> None:
        self.errors.append({"code": code, "message": message, **({"step": step} if step else {})})


def resolve_options(request: ChatRequest, runtime) -> EffectiveOptions:  # noqa: ANN001
    s = request.settings
    rt = runtime.current
    return EffectiveOptions(
        model=s.model or rt.chat_model,
        temperature=s.temperature if s.temperature is not None else rt.temperature,
        max_tokens=s.max_tokens or rt.max_tokens,
        timeout_s=rt.llm_timeout_s,
        top_k=s.top_k or rt.rag_top_k,
        score_threshold=s.score_threshold if s.score_threshold is not None else rt.rag_score_threshold,
        search_results=s.search_results or runtime.settings.search_results,
        document_ids=s.document_ids,
    )
