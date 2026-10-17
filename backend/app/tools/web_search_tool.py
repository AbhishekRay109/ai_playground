"""Web search tool (SearXNG + SSRF-safe page fetching)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.chat import Source, ToolName
from app.services.citations import excerpt
from app.tools.base import Evidence, Tool, ToolContext, ToolOutput, bound


class WebSearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=300, description="Web search query")
    max_results: int | None = Field(default=None, ge=1, le=10, description="Number of search results")


class WebSearchTool(Tool):
    name = ToolName.WEB_SEARCH
    description = "Search the public web via the local SearXNG instance and read the top pages."
    args_model = WebSearchArgs

    async def run(self, args: WebSearchArgs, ctx: ToolContext) -> ToolOutput:  # type: ignore[override]
        c = ctx.container
        outcome = await c.search.search_and_fetch(
            ctx.question, query=args.query, max_results=args.max_results or ctx.options.search_results
        )
        fetched = {p.url: p for p in outcome.pages}
        results_detail = [
            {
                "title": r.title,
                "url": r.url,
                "snippet": r.snippet,
                "engine": r.engine,
                "published_date": r.published_date,
                "fetch_status": fetched[r.url].status if r.url in fetched else "not_fetched",
                "fetch_error": fetched[r.url].error if r.url in fetched else None,
                "final_url": fetched[r.url].final_url if r.url in fetched else None,
            }
            for r in outcome.results
        ]
        details = {
            "query": outcome.query,
            "results": results_detail,
            "notes": outcome.notes,
            "search_latency_ms": outcome.search_latency_ms,
            "fetch_latency_ms": outcome.fetch_latency_ms,
        }
        evidence = [
            Evidence(
                source=Source(
                    id=0,
                    kind="web",
                    title=ev.title,
                    url=ev.url,
                    excerpt=excerpt(ev.text, ctx.question),
                    content_type=ev.content_type,
                    engine=ev.engine,
                    published_date=ev.published_date,
                ),
                text=ev.text,
            )
            for ev in outcome.evidence
        ]
        n_pages = sum(1 for ev in outcome.evidence if ev.content_type == "page")
        summary = (
            f"{len(outcome.results)} search result(s); read {n_pages} page(s), "
            f"{len(evidence) - n_pages} snippet(s) used"
        )
        observation = "\n".join(
            f"- {ev.title} <{ev.url}> [{ev.content_type}]: {ev.text[:300]}" for ev in outcome.evidence
        )
        return ToolOutput(
            summary=summary,
            observation=bound(observation or "No results.", c.settings.tool_output_max_chars),
            evidence=evidence,
            details=details,
            counts={"web_sources": len(evidence)},
        )
