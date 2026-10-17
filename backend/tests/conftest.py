"""Shared fixtures. All external boundaries (Ollama, SearXNG, the web, embedding weights)
are replaced by deterministic fakes; Qdrant runs for real in local (embedded) mode."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.container import Container, build_container
from app.main import create_app
from app.services.llm_service import ChatMessage, ScriptedLLM


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,  # ignore any developer .env
        environment="test",
        data_dir=tmp_path / "data",
        embedding_provider="hash",
        embedding_model="hash-384",
        ollama_model="test-model",
        rag_score_threshold=0.05,
        chunk_size=200,
        chunk_overlap=30,
        rate_limit_per_minute=0,
        web_respect_robots=False,
        agent_tool_timeout_s=5,
        agent_request_timeout_s=20,
        searxng_url="http://searxng.test",
    )


class WebMock:
    """Configurable fake for SearXNG and public web pages (an httpx MockTransport)."""

    def __init__(self) -> None:
        self.search_results: list[dict[str, Any]] = []
        self.pages: dict[str, httpx.Response | Callable[[httpx.Request], httpx.Response]] = {}
        self.search_status = 200
        self.search_error: Exception | None = None
        self.requests: list[str] = []

    def searxng_handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        if self.search_error:
            raise self.search_error
        if request.url.path == "/healthz":
            return httpx.Response(200, text="OK")
        if self.search_status != 200:
            return httpx.Response(self.search_status, text="error")
        return httpx.Response(200, json={"query": request.url.params.get("q"), "results": self.search_results})

    def web_handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        page = self.pages.get(str(request.url))
        if page is None:
            return httpx.Response(404, text="not found")
        return page(request) if callable(page) else page


@pytest.fixture
def web() -> WebMock:
    return WebMock()


@pytest.fixture
def llm() -> ScriptedLLM:
    return ScriptedLLM()


@pytest.fixture
def container(settings: Settings, llm: ScriptedLLM, web: WebMock) -> Iterator[Container]:
    c = build_container(
        settings,
        llm=llm,
        searxng_transport=httpx.MockTransport(web.searxng_handler),
        web_transport=httpx.MockTransport(web.web_handler),
    )
    # Fake DNS: every test hostname resolves to a public address.
    c.search.fetcher.policy.resolver = lambda host, port: ["93.184.216.34"]
    yield c
    c.close()


@pytest.fixture
def client(container: Container) -> Iterator[TestClient]:
    app = create_app(container=container)
    with TestClient(app) as tc:
        yield tc


def system_prompt(messages: list[ChatMessage]) -> str:
    return messages[0].content if messages and messages[0].role == "system" else ""


def planner(decisions: list[dict[str, Any]], answer: str = "Final answer.") -> Callable[[list[ChatMessage]], str]:
    """An LLM script for the agent: returns planner decisions in order, then ``answer``
    for synthesis calls. When decisions run out, the planner chooses final_answer."""
    queue = list(decisions)

    def respond(messages: list[ChatMessage]) -> str:
        sp = system_prompt(messages)
        if "planning step" in sp:
            if queue:
                return json.dumps(queue.pop(0))
            return json.dumps({"action": "final_answer", "tool": "none", "arguments": {}, "purpose": "done"})
        return answer

    return respond


def sse_events(text: str) -> list[dict[str, Any]]:
    events = []
    for block in text.strip().split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


SAMPLE_MD = """# Acme Travel Policy

## Booking
International travel must be booked at least 21 days in advance and requires director approval.
Domestic trips must be booked at least 7 days in advance.

## Exclusions
Traffic fines, parking tickets and personal entertainment are excluded and will not be reimbursed.

## Meals
The international per diem is 85 USD per day.
"""
