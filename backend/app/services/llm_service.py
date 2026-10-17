"""Client for a locally running Ollama server.

Only the Ollama HTTP API is used (``/api/tags``, ``/api/chat``). There is deliberately no
fallback to any hosted LLM: if Ollama is unreachable the caller gets an
:class:`~app.core.errors.LLMUnavailable` error with setup hints.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.core.errors import LLMError, LLMModelNotFound, LLMTimeout, LLMUnavailable
from app.core.logging import get_logger
from app.schemas.common import ModelInfo

log = get_logger(__name__)


@dataclass
class LLMOptions:
    model: str
    temperature: float = 0.2
    max_tokens: int = 1024
    timeout_s: float = 120.0
    # JSON schema (dict) for structured output, or "json" for free-form JSON.
    format: dict[str, Any] | str | None = None


@dataclass
class LLMResult:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_tokens: bool = False
    latency_ms: int = 0


@dataclass
class LLMChunk:
    delta: str = ""
    done: bool = False
    result: LLMResult | None = None  # set on the final chunk


@dataclass
class ChatMessage:
    role: str  # system | user | assistant
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


class LLMClient(Protocol):
    async def list_models(self) -> list[ModelInfo]: ...

    async def chat(self, messages: list[ChatMessage], options: LLMOptions) -> LLMResult: ...

    def stream_chat(self, messages: list[ChatMessage], options: LLMOptions) -> AsyncIterator[LLMChunk]: ...


def estimate_tokens(text: str) -> int:
    """Rough token estimate (≈4 characters per token) for models that do not report usage."""
    return max(1, len(text) // 4) if text else 0


SETUP_HINT = (
    "Start Ollama (`ollama serve`) and pull a model, e.g. `ollama pull qwen2.5:7b`. "
    "Check OLLAMA_BASE_URL if Ollama runs on another host or port."
)


class OllamaClient:
    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._transport = transport

    def _client(self, timeout: float) -> httpx.AsyncClient:
        # Ollama is a local service: do not route through HTTP proxies from the environment.
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout, connect=min(5.0, timeout)),
            transport=self._transport,
            trust_env=False,
        )

    async def list_models(self, timeout: float = 5.0) -> list[ModelInfo]:
        try:
            async with self._client(timeout) as client:
                resp = await client.get("/api/tags")
        except httpx.TimeoutException as exc:
            raise LLMTimeout("Timed out contacting Ollama.", hint=SETUP_HINT) from exc
        except httpx.TransportError as exc:
            raise LLMUnavailable(f"Ollama is not reachable at {self.base_url}.", hint=SETUP_HINT) from exc
        if resp.status_code != 200:
            raise LLMError(f"Ollama returned HTTP {resp.status_code} when listing models.")
        models = []
        for m in resp.json().get("models", []):
            details = m.get("details") or {}
            models.append(
                ModelInfo(
                    name=m.get("name") or m.get("model", "unknown"),
                    size_bytes=m.get("size"),
                    family=details.get("family"),
                    parameter_size=details.get("parameter_size"),
                    quantization=details.get("quantization_level"),
                    modified_at=m.get("modified_at"),
                )
            )
        return models

    def _payload(self, messages: list[ChatMessage], options: LLMOptions, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": options.model,
            "messages": [m.to_dict() for m in messages],
            "stream": stream,
            "options": {"temperature": options.temperature, "num_predict": options.max_tokens},
        }
        if options.format is not None:
            payload["format"] = options.format
        return payload

    @staticmethod
    def _raise_for_status(status: int, body: str, model: str) -> None:
        if status == 200:
            return
        detail = ""
        try:
            detail = json.loads(body).get("error", "")
        except (ValueError, AttributeError):
            detail = body[:200]
        if status == 404 or "not found" in detail.lower():
            raise LLMModelNotFound(
                f"Model '{model}' is not installed in Ollama.",
                hint=f"Run `ollama pull {model}` or choose an installed model in Settings.",
            )
        raise LLMError(f"Ollama returned HTTP {status}: {detail[:200]}")

    async def chat(self, messages: list[ChatMessage], options: LLMOptions) -> LLMResult:
        start = time.perf_counter()
        try:
            async with self._client(options.timeout_s) as client:
                resp = await client.post("/api/chat", json=self._payload(messages, options, stream=False))
        except httpx.TimeoutException as exc:
            raise LLMTimeout(
                f"The model did not respond within {options.timeout_s:.0f}s.",
                hint="Increase the request timeout in Settings or use a smaller model.",
            ) from exc
        except httpx.TransportError as exc:
            raise LLMUnavailable(f"Ollama is not reachable at {self.base_url}.", hint=SETUP_HINT) from exc
        self._raise_for_status(resp.status_code, resp.text, options.model)
        data = resp.json()
        text = (data.get("message") or {}).get("content", "")
        return self._result(data, text, options, messages, start)

    async def stream_chat(self, messages: list[ChatMessage], options: LLMOptions) -> AsyncIterator[LLMChunk]:
        start = time.perf_counter()
        parts: list[str] = []
        try:
            async with self._client(options.timeout_s) as client:
                async with client.stream(
                    "POST", "/api/chat", json=self._payload(messages, options, stream=True)
                ) as resp:
                    if resp.status_code != 200:
                        body = (await resp.aread()).decode("utf-8", "replace")
                        self._raise_for_status(resp.status_code, body, options.model)
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                        except ValueError:
                            continue
                        if data.get("error"):
                            raise LLMError(f"Ollama error: {str(data['error'])[:200]}")
                        delta = (data.get("message") or {}).get("content", "")
                        if delta:
                            parts.append(delta)
                            yield LLMChunk(delta=delta)
                        if data.get("done"):
                            yield LLMChunk(
                                done=True,
                                result=self._result(data, "".join(parts), options, messages, start),
                            )
                            return
        except httpx.TimeoutException as exc:
            raise LLMTimeout(
                f"The model did not respond within {options.timeout_s:.0f}s.",
                hint="Increase the request timeout in Settings or use a smaller model.",
            ) from exc
        except httpx.TransportError as exc:
            raise LLMUnavailable(f"Ollama is not reachable at {self.base_url}.", hint=SETUP_HINT) from exc
        # Stream ended without a done marker: return what we have.
        yield LLMChunk(done=True, result=self._result({}, "".join(parts), options, messages, start))

    @staticmethod
    def _result(data: dict, text: str, options: LLMOptions, messages: list[ChatMessage], start: float) -> LLMResult:
        prompt_tokens = data.get("prompt_eval_count")
        completion_tokens = data.get("eval_count")
        estimated = prompt_tokens is None or completion_tokens is None
        if prompt_tokens is None:
            prompt_tokens = sum(estimate_tokens(m.content) for m in messages)
        if completion_tokens is None:
            completion_tokens = estimate_tokens(text)
        return LLMResult(
            text=text,
            model=data.get("model", options.model),
            prompt_tokens=int(prompt_tokens),
            completion_tokens=int(completion_tokens),
            estimated_tokens=estimated,
            latency_ms=int((time.perf_counter() - start) * 1000),
        )


@dataclass
class ScriptedLLM:
    """Deterministic LLM used by tests and the offline evaluation demo.

    ``responses`` is consumed in order; each item is either a string, or a callable that
    receives the message list and returns a string. When exhausted, ``responder`` (a callable)
    or else ``default`` is used.
    """

    responses: list[Any] = field(default_factory=list)
    responder: Any = None
    default: str = "This is a scripted answer."
    model_name: str = "scripted-test-model"
    calls: list[list[ChatMessage]] = field(default_factory=list)
    delay_s: float = 0.0
    fail_with: Exception | None = None

    async def list_models(self) -> list[ModelInfo]:
        if self.fail_with:
            raise self.fail_with
        return [ModelInfo(name=self.model_name)]

    def _next(self, messages: list[ChatMessage]) -> str:
        self.calls.append(messages)
        if self.responses:
            item = self.responses.pop(0)
            return item(messages) if callable(item) else str(item)
        if self.responder is not None:
            return self.responder(messages)
        return self.default

    async def chat(self, messages: list[ChatMessage], options: LLMOptions) -> LLMResult:
        import asyncio

        if self.fail_with:
            raise self.fail_with
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        text = self._next(messages)
        return LLMResult(text=text, model=options.model, prompt_tokens=10, completion_tokens=estimate_tokens(text))

    async def stream_chat(self, messages: list[ChatMessage], options: LLMOptions) -> AsyncIterator[LLMChunk]:
        import asyncio

        if self.fail_with:
            raise self.fail_with
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        text = self._next(messages)
        for i in range(0, len(text), 12):
            yield LLMChunk(delta=text[i : i + 12])
        yield LLMChunk(
            done=True,
            result=LLMResult(text=text, model=options.model, prompt_tokens=10, completion_tokens=estimate_tokens(text)),
        )
