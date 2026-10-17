"""Manual execution modes. Each runs exactly one strategy and nothing else.

* Direct LLM: the local model only (no retrieval, search, SQL or agent).
* Document RAG: document retrieval → grounded generation.
* Web Search: SearXNG + page fetching → grounded generation.
* SQL Assistant: validated read-only SQL → explanation of the result rows.
"""

from __future__ import annotations

from app.services.llm_service import ChatMessage
from app.services.modes.common import ModeContext, finalize_answer, register_evidence, run_tool, stream_llm
from app.services.prompts import (
    DIRECT_SYSTEM,
    INSUFFICIENT_DOCS,
    INSUFFICIENT_WEB,
    RAG_SYSTEM,
    SQL_ANSWER_SYSTEM,
    WEB_SYSTEM,
    evidence_user_prompt,
    format_evidence,
)
from app.tools.document_tool import DocumentArgs, DocumentRetrievalTool
from app.tools.sql_tool import SqlArgs, SqlTool
from app.tools.web_search_tool import WebSearchArgs, WebSearchTool


async def run_direct(ctx: ModeContext) -> None:
    messages = [ChatMessage("system", DIRECT_SYSTEM), *ctx.history, ChatMessage("user", ctx.request.question)]
    text = await stream_llm(ctx, messages, ctx.llm_options(), purpose="Answer directly from the local model")
    ctx.recorder.answer = text


async def run_rag(ctx: ModeContext) -> None:
    rec = ctx.recorder
    s = ctx.container.settings
    output = await run_tool(
        ctx,
        DocumentRetrievalTool(),
        DocumentArgs(query=ctx.request.question),
        purpose="Find relevant passages in uploaded documents",
        timeout_s=s.agent_tool_timeout_s,
        raise_errors=True,
    )
    assert output is not None
    if not output.evidence:
        reason = output.details.get("notes") or []
        n_docs = output.details.get("documents_indexed", 0)
        explanation = (
            "No documents have been uploaded yet. Upload files in the Documents panel."
            if n_docs == 0
            else "No passage was similar enough to the question"
            + (f" ({reason[0]})." if reason else ".")
            + " Try rephrasing, or lower the similarity threshold in Settings."
        )
        rec.answer = f"{INSUFFICIENT_DOCS}\n\n{explanation}"
        rec.delta(rec.answer)
        rec.warnings.append("No evidence retrieved; the model was not called.")
        return
    items = register_evidence(rec, output.evidence)
    prompt = evidence_user_prompt(ctx.request.question, format_evidence(items, s.evidence_max_chars))
    messages = [ChatMessage("system", RAG_SYSTEM), ChatMessage("user", prompt)]
    text = await stream_llm(
        ctx, messages, ctx.llm_options(), purpose="Generate an answer grounded in the retrieved chunks"
    )
    finalize_answer(ctx, text)


async def run_web(ctx: ModeContext) -> None:
    rec = ctx.recorder
    s = ctx.container.settings
    output = await run_tool(
        ctx,
        WebSearchTool(),
        WebSearchArgs(query=ctx.request.question),
        purpose="Search the web and read the top results",
        timeout_s=s.agent_tool_timeout_s,
        raise_errors=True,
    )
    assert output is not None
    if not output.evidence:
        rec.answer = INSUFFICIENT_WEB + " The search returned no usable results."
        rec.delta(rec.answer)
        rec.warnings.append("No web evidence retrieved; the model was not called.")
        return
    items = register_evidence(rec, output.evidence)
    prompt = evidence_user_prompt(ctx.request.question, format_evidence(items, s.evidence_max_chars))
    messages = [ChatMessage("system", WEB_SYSTEM), ChatMessage("user", prompt)]
    text = await stream_llm(ctx, messages, ctx.llm_options(), purpose="Generate an answer grounded in web sources")
    finalize_answer(ctx, text)


async def run_sql(ctx: ModeContext) -> None:
    rec = ctx.recorder
    s = ctx.container.settings
    output = await run_tool(
        ctx,
        SqlTool(),
        SqlArgs(question=ctx.request.question),
        purpose="Generate, validate and run a read-only SQL query",
        timeout_s=s.agent_tool_timeout_s,
        raise_errors=True,
    )
    assert output is not None
    if output.status != "success":
        rec.status = "error"
        sql = output.details.get("sql")
        rec.answer = f"I could not answer this from the sample database: {output.error}" + (
            f"\n\nThe rejected query was:\n```sql\n{sql}\n```" if sql else ""
        )
        rec.delta(rec.answer)
        return
    items = register_evidence(rec, output.evidence)
    prompt = evidence_user_prompt(ctx.request.question, format_evidence(items, s.evidence_max_chars))
    messages = [ChatMessage("system", SQL_ANSWER_SYSTEM), ChatMessage("user", prompt)]
    text = await stream_llm(ctx, messages, ctx.llm_options(), purpose="Explain the query result")
    finalize_answer(ctx, text)
