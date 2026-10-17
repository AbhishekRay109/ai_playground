"""Web search through a self-hosted SearXNG instance, plus evidence selection from pages."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field

import httpx

from app.core.config import Settings
from app.core.errors import SearchRateLimited, SearchUnavailable
from app.core.logging import get_logger
from app.services.embedding_service import tokenize
from app.services.web_fetcher import FetchedPage, WebFetcher

log = get_logger(__name__)

SEARXNG_HINT = (
    "Start SearXNG (see docker-compose.yml, service 'searxng') and make sure `json` is listed under "
    "`search.formats` in its settings.yml. Check SEARXNG_URL."
)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    engine: str | None = None
    published_date: str | None = None


@dataclass
class WebEvidence:
    url: str
    title: str
    text: str
    content_type: str  # page | snippet
    engine: str | None = None
    published_date: str | None = None


@dataclass
class WebSearchOutcome:
    query: str
    results: list[SearchResult]
    pages: list[FetchedPage]
    evidence: list[WebEvidence]
    search_latency_ms: int = 0
    fetch_latency_ms: int = 0
    notes: list[str] = field(default_factory=list)


class SearxngClient:
    def __init__(self, base_url: str, timeout_s: float, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._transport = transport

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        params = {"q": query, "format": "json", "safesearch": "1", "language": "auto"}
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout_s, transport=self._transport, trust_env=False
            ) as client:
                resp = await client.get("/search", params=params)
        except httpx.TimeoutException as exc:
            raise SearchUnavailable("SearXNG did not respond in time.", hint=SEARXNG_HINT) from exc
        except httpx.TransportError as exc:
            raise SearchUnavailable(f"SearXNG is not reachable at {self.base_url}.", hint=SEARXNG_HINT) from exc
        if resp.status_code == 429:
            raise SearchRateLimited("SearXNG is rate limiting requests. Try again shortly.", hint=SEARXNG_HINT)
        if resp.status_code == 403:
            raise SearchUnavailable("SearXNG refused the JSON API request.", hint=SEARXNG_HINT)
        if resp.status_code != 200:
            raise SearchUnavailable(f"SearXNG returned HTTP {resp.status_code}.", hint=SEARXNG_HINT)
        try:
            data = resp.json()
        except ValueError as exc:
            raise SearchUnavailable("SearXNG returned a non-JSON response.", hint=SEARXNG_HINT) from exc
        results: list[SearchResult] = []
        seen: set[str] = set()
        for item in data.get("results", []):
            url = str(item.get("url") or "")
            if not url.startswith(("http://", "https://")) or url in seen:
                continue
            seen.add(url)
            engines = item.get("engines") or ([item["engine"]] if item.get("engine") else [])
            results.append(
                SearchResult(
                    title=str(item.get("title") or url)[:300],
                    url=url,
                    snippet=str(item.get("content") or "")[:1000],
                    engine=", ".join(engines) if engines else None,
                    published_date=item.get("publishedDate") or None,
                )
            )
            if len(results) >= limit:
                break
        return results

    async def health(self) -> tuple[bool, str]:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=3.0, transport=self._transport, trust_env=False
            ) as client:
                resp = await client.get("/healthz")
            return resp.status_code == 200, f"HTTP {resp.status_code}"
        except httpx.HTTPError as exc:
            return False, type(exc).__name__


def make_search_query(question: str) -> str:
    """Use the question as the query, trimmed to a sensible length."""
    q = " ".join(question.split())
    return q[:300]


def select_passages(text: str, question: str, max_chars: int) -> str:
    """Pick the paragraphs most related to the question, preserving their original order."""
    paragraphs = [p.strip() for p in re.split(r"\n+", text) if len(p.strip()) > 30]
    if not paragraphs:
        return text[:max_chars]
    q_terms = set(tokenize(question))
    scored = []
    for i, p in enumerate(paragraphs):
        overlap = len(q_terms & set(tokenize(p)))
        scored.append((overlap, -i, i, p))
    scored.sort(reverse=True)
    chosen: list[tuple[int, str]] = []
    used = 0
    for overlap, _neg, i, p in scored:
        if used >= max_chars:
            break
        if overlap == 0 and chosen:
            break
        piece = p[: max_chars - used]
        chosen.append((i, piece))
        used += len(piece)
    chosen.sort()
    return "\n".join(p for _, p in chosen)


class SearchService:
    def __init__(self, settings: Settings, searxng: SearxngClient, fetcher: WebFetcher) -> None:
        self.settings = settings
        self.searxng = searxng
        self.fetcher = fetcher

    async def search_and_fetch(
        self, question: str, *, query: str | None = None, max_results: int | None = None, fetch_pages: int | None = None
    ) -> WebSearchOutcome:
        query = make_search_query(query or question)
        limit = max_results or self.settings.search_results
        t0 = time.perf_counter()
        results = await self.searxng.search(query, limit)
        search_ms = int((time.perf_counter() - t0) * 1000)
        n_fetch = min(fetch_pages if fetch_pages is not None else self.settings.web_fetch_pages, len(results))
        t1 = time.perf_counter()
        pages: list[FetchedPage] = []
        if n_fetch:
            pages = list(await asyncio.gather(*(self.fetcher.fetch(r.url) for r in results[:n_fetch])))
        fetch_ms = int((time.perf_counter() - t1) * 1000)
        page_by_url = {p.url: p for p in pages}

        evidence: list[WebEvidence] = []
        notes: list[str] = []
        for r in results:
            page = page_by_url.get(r.url)
            if page and page.ok and len(page.text.strip()) > 100:
                body = select_passages(page.text, question, self.settings.web_max_chars_per_page)
                evidence.append(
                    WebEvidence(
                        url=r.url,
                        title=page.title or r.title,
                        text=body,
                        content_type="page",
                        engine=r.engine,
                        published_date=r.published_date,
                    )
                )
            elif r.snippet:
                if page and not page.ok:
                    notes.append(f"Could not use page {r.url}: {page.error or page.status}; using snippet")
                evidence.append(
                    WebEvidence(
                        url=r.url,
                        title=r.title,
                        text=r.snippet,
                        content_type="snippet",
                        engine=r.engine,
                        published_date=r.published_date,
                    )
                )
        if not results:
            notes.append("The search returned no results.")
        return WebSearchOutcome(
            query=query,
            results=results,
            pages=pages,
            evidence=evidence,
            search_latency_ms=search_ms,
            fetch_latency_ms=fetch_ms,
            notes=notes,
        )
