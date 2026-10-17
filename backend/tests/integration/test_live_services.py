"""Optional integration tests against locally running services.

Run with:  RUN_INTEGRATION=1 pytest tests/integration -m integration
Requires: Ollama with OLLAMA_MODEL pulled, the embedding model cached locally
(`python -m app.cli download-embedding-model`), and optionally SearXNG at SEARXNG_URL.
"""

from __future__ import annotations

import os

import httpx
import pytest

from app.core.config import Settings
from app.core.container import build_container
from app.schemas.chat import ChatRequest, Mode, ToolName
from app.services.chat_service import ChatService
from app.services.llm_service import ChatMessage, LLMOptions, OllamaClient

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1 to run"),
]


@pytest.fixture
def live_settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path / "data", rate_limit_per_minute=0)


async def test_ollama_lists_and_chats(live_settings):
    client = OllamaClient(live_settings.ollama_base_url)
    names = [m.name for m in await client.list_models()]
    assert live_settings.ollama_model in names, f"pull it first: ollama pull {live_settings.ollama_model}"
    result = await client.chat(
        [ChatMessage("user", "Reply with the single word: pong")],
        LLMOptions(model=live_settings.ollama_model, max_tokens=10),
    )
    assert result.text.strip()


async def test_rag_end_to_end_with_real_embeddings(live_settings):
    c = build_container(live_settings)
    try:
        text = b"The Zephyr-9 drone has a maximum flight time of 47 minutes and weighs 1.2 kg."
        res = await c.documents.ingest("zephyr.txt", text)
        assert res.status == "ready"
        resp = await ChatService(c).execute(
            ChatRequest(question="What is the Zephyr-9 flight time?", mode=Mode.DOCUMENT_RAG), persist=False
        )
        assert resp.sources and resp.sources[0].filename == "zephyr.txt"
        assert "47" in resp.answer
    finally:
        c.close()


async def test_agent_calculator_with_real_model(live_settings):
    c = build_container(live_settings)
    try:
        resp = await ChatService(c).execute(
            ChatRequest(question="What is 129 * 347?", mode=Mode.AGENT, enabled_tools=[ToolName.CALCULATOR]),
            persist=False,
        )
        assert resp.status in ("success", "partial")
        assert "44763" in resp.answer.replace(",", "")
    finally:
        c.close()


async def test_searxng_search(live_settings):
    try:
        httpx.get(live_settings.searxng_url, timeout=2)
    except httpx.HTTPError:
        pytest.skip("SearXNG not running")
    c = build_container(live_settings)
    try:
        outcome = await c.search.search_and_fetch("Python programming language", fetch_pages=1)
        assert outcome.results
    finally:
        c.close()
