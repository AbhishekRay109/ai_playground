"""Helpers shared by execution modes: running tools with tracing, numbering evidence,
streaming LLM output and validating citations."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from pydantic import BaseModel

from app.core.container import Container
from app.core.errors import AppError, ToolTimeout
from app.core.logging import get_logger
from app.schemas.chat import ChatRequest
from app.services.citations import validate_citations
from app.services.execution import EffectiveOptions, RunRecorder
from app.services.llm_service import ChatMessage, LLMOptions, LLMResult
from app.services.prompts import EvidenceItem
from app.tools.base import Evidence, Tool, ToolContext, ToolOutput

log = get_logger(__name__)


@dataclass
class ModeContext:
    container: Container
    request: ChatRequest
    options: EffectiveOptions
    recorder: RunRecorder
    history: list[ChatMessage] = field(default_factory=list)

    def llm_options(self, **overrides) -> LLMOptions:  # noqa: ANN003
        o = self.options
        base = {"model": o.model, "temperature": o.temperature, "max_tokens": o.max_tokens, "timeout_s": o.timeout_s}
        base.update(overrides)
        return LLMOptions(**base)

    def tool_context(self) -> ToolContext:
        return ToolContext(container=self.container, options=self.options, question=self.request.question)


async def run_tool(
    ctx: ModeContext, tool: Tool, args: BaseModel, *, purpose: str, timeout_s: float, raise_errors: bool
) -> ToolOutput | None:
    """Execute a tool with a trace step and a timeout.

    Returns the output, or ``None`` when the tool failed (and ``raise_errors`` is False).
    """
    rec = ctx.recorder
    step = rec.start_step("tool", tool.name.value, purpose=purpose, input_summary=tool.input_summary(args))
    try:
        output = await asyncio.wait_for(tool.run(args, ctx.tool_context()), timeout=timeout_s)
    except TimeoutError:
        rec.finish_step(step, "timeout", f"Timed out after {timeout_s:g}s")
        rec.add_error("tool_timeout", f"{tool.name.value} timed out after {timeout_s:g}s", step.id)
        if raise_errors:
            raise ToolTimeout(f"The {tool.name.value} tool timed out after {timeout_s:g}s.") from None
        return None
    except AppError as exc:
        rec.finish_step(step, "error", exc.message, {"error_code": exc.code, "hint": exc.hint})
        rec.add_error(exc.code, exc.message, step.id)
        if raise_errors:
            raise
        return None
    except Exception as exc:  # noqa: BLE001
        log.exception("tool %s failed", tool.name.value)
        rec.finish_step(step, "error", "Unexpected tool error", {"error_code": "tool_error"})
        rec.add_error("tool_error", f"{tool.name.value} failed unexpectedly", step.id)
        if raise_errors:
            raise AppError("The tool failed unexpectedly.", code="tool_error") from exc
        return None
    for r in output.llm_results:
        rec.add_llm_usage(r)
    for key, value in output.counts.items():
        setattr(rec.counts, key, getattr(rec.counts, key) + value)
    if output.embedding_model:
        rec.embedding_model = output.embedding_model
    rec.finish_step(step, "success" if output.status == "success" else "error", output.summary, output.details)
    if output.status != "success" and output.error:
        rec.add_error("tool_error", output.error, step.id)
    return output


def register_evidence(rec: RunRecorder, evidence: list[Evidence]) -> list[EvidenceItem]:
    """Assign citation numbers (continuing across tools) and publish the sources."""
    items: list[EvidenceItem] = []
    sources = []
    next_id = len(rec.sources) + 1
    for ev in evidence:
        ev.source.id = next_id
        sources.append(ev.source)
        meta = {"page": ev.source.page, "content_type": ev.source.content_type}
        items.append(
            EvidenceItem(
                id=next_id, kind=ev.source.kind, title=ev.source.url or ev.source.title, text=ev.text, meta=meta
            )
        )
        next_id += 1
    if sources:
        rec.add_sources(sources)
    return items


async def stream_llm(ctx: ModeContext, messages: list[ChatMessage], options: LLMOptions, *, purpose: str) -> str:
    """Stream a model response to the client, recording an LLM step."""
    rec = ctx.recorder
    step = rec.start_step("llm", "llm", purpose=purpose, input_summary=f"model={options.model}")
    parts: list[str] = []
    result: LLMResult | None = None
    try:
        async for chunk in ctx.container.llm.stream_chat(messages, options):
            if chunk.delta:
                parts.append(chunk.delta)
                rec.delta(chunk.delta)
            if chunk.done:
                result = chunk.result
    except AppError as exc:
        rec.finish_step(step, "error", exc.message, {"error_code": exc.code})
        raise
    except asyncio.CancelledError:
        rec.finish_step(step, "skipped", "Cancelled by user")
        raise
    text = "".join(parts)
    if result:
        rec.add_llm_usage(result)
    rec.finish_step(
        step,
        "success",
        f"Generated {len(text)} characters",
        {"model": options.model, "completion_tokens": result.completion_tokens if result else None},
    )
    return text


def finalize_answer(ctx: ModeContext, text: str) -> None:
    """Validate citations against the sources retrieved in this execution."""
    rec = ctx.recorder
    if rec.sources:
        cleaned, report = validate_citations(text, rec.sources)
        rec.citations = report
        if report.invalid_markers:
            rec.warnings.append(
                f"Removed citation(s) {report.invalid_markers} that did not match any retrieved source."
            )
        if report.total_markers == 0:
            rec.warnings.append("The model did not cite any source.")
        rec.answer = cleaned
    else:
        rec.answer = text
