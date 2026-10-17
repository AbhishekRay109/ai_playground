import json

import httpx
import pytest

from app.core.errors import LLMModelNotFound, LLMTimeout, LLMUnavailable
from app.services.llm_service import ChatMessage, LLMOptions, OllamaClient

OPTS = LLMOptions(model="llama3.2:3b", temperature=0.1, max_tokens=64, timeout_s=5)


def client_with(handler) -> OllamaClient:
    return OllamaClient("http://ollama.test", transport=httpx.MockTransport(handler))


async def test_list_models():
    def handler(req):
        assert req.url.path == "/api/tags"
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "name": "llama3.2:3b",
                        "size": 2_000_000_000,
                        "details": {"family": "llama", "parameter_size": "3.2B", "quantization_level": "Q4_K_M"},
                    }
                ]
            },
        )

    models = await client_with(handler).list_models()
    assert models[0].name == "llama3.2:3b" and models[0].parameter_size == "3.2B"


async def test_chat_sends_options_and_parses_usage():
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(
            200,
            json={
                "model": "llama3.2:3b",
                "message": {"role": "assistant", "content": "Hi!"},
                "done": True,
                "prompt_eval_count": 12,
                "eval_count": 3,
            },
        )

    result = await client_with(handler).chat([ChatMessage("user", "hello")], OPTS)
    assert result.text == "Hi!" and result.prompt_tokens == 12 and result.completion_tokens == 3
    assert not result.estimated_tokens
    assert seen["options"] == {"temperature": 0.1, "num_predict": 64}
    assert seen["stream"] is False


async def test_stream_chat_yields_deltas_then_result():
    lines = [
        {"message": {"content": "Hel"}, "done": False},
        {"message": {"content": "lo"}, "done": False},
        {"message": {"content": ""}, "done": True, "model": "m", "prompt_eval_count": 5, "eval_count": 2},
    ]

    def handler(_req):
        return httpx.Response(200, content="\n".join(json.dumps(x) for x in lines).encode())

    chunks = [c async for c in client_with(handler).stream_chat([ChatMessage("user", "hi")], OPTS)]
    assert "".join(c.delta for c in chunks) == "Hello"
    assert chunks[-1].done and chunks[-1].result.completion_tokens == 2


async def test_model_not_found():
    def handler(_req):
        return httpx.Response(404, json={"error": "model 'nope' not found, try pulling it first"})

    with pytest.raises(LLMModelNotFound) as exc:
        await client_with(handler).chat([ChatMessage("user", "x")], LLMOptions(model="nope"))
    assert "ollama pull nope" in exc.value.hint


async def test_ollama_unreachable():
    def handler(req):
        raise httpx.ConnectError("refused", request=req)

    with pytest.raises(LLMUnavailable) as exc:
        await client_with(handler).chat([ChatMessage("user", "x")], OPTS)
    assert "ollama serve" in exc.value.hint
    with pytest.raises(LLMUnavailable):
        [c async for c in client_with(handler).stream_chat([ChatMessage("user", "x")], OPTS)]


async def test_ollama_timeout():
    def handler(req):
        raise httpx.ReadTimeout("slow", request=req)

    with pytest.raises(LLMTimeout):
        await client_with(handler).chat([ChatMessage("user", "x")], OPTS)


async def test_token_estimate_when_usage_missing():
    def handler(_req):
        return httpx.Response(200, json={"message": {"content": "abcd" * 10}, "done": True})

    result = await client_with(handler).chat([ChatMessage("user", "x" * 40)], OPTS)
    assert result.estimated_tokens and result.completion_tokens == 10
