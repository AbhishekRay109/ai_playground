"""Chat orchestration: session handling, mode dispatch, event streaming and persistence."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from app.agents.graph import run_agent
from app.core.container import Container
from app.core.errors import AppError, ValidationFailed
from app.core.logging import get_logger, redact
from app.schemas.chat import ChatRequest, ChatResponse, Mode
from app.services.execution import RunRecorder, resolve_options
from app.services.llm_service import ChatMessage
from app.services.modes.common import ModeContext
from app.services.modes.manual import run_direct, run_rag, run_sql, run_web

log = get_logger(__name__)

MODE_RUNNERS: dict[Mode, Callable[[ModeContext], Awaitable[None]]] = {
    Mode.DIRECT: run_direct,
    Mode.DOCUMENT_RAG: run_rag,
    Mode.WEB_SEARCH: run_web,
    Mode.SQL: run_sql,
    Mode.AGENT: run_agent,
}

_DONE = object()


class ChatService:
    def __init__(self, container: Container) -> None:
        self.c = container

    def _validate(self, req: ChatRequest) -> None:
        limit = self.c.settings.max_question_chars
        if len(req.question) > limit:
            raise ValidationFailed(f"The question is too long ({len(req.question)} > {limit} characters).")
        if req.mode != Mode.AGENT and req.enabled_tools:
            # Tool toggles only apply to Agent Mode; manual modes run exactly one strategy.
            req.enabled_tools = []

    async def stream(self, req: ChatRequest, *, persist: bool = True) -> AsyncIterator[dict[str, Any]]:
        """Run a request and yield typed events, ending with ``done`` or ``error``."""
        started = time.perf_counter()
        self._validate(req)
        repo = self.c.sessions_repo
        session_id: str | None = None
        history: list[ChatMessage] = []
        if persist:
            if req.session_id and repo.exists(req.session_id):
                history = [
                    ChatMessage(m.role, m.content)
                    for m in repo.recent_messages(req.session_id, self.c.settings.llm_history_messages)
                ]
            session = repo.get_or_create(req.session_id, req.question)
            session_id = session.id
            repo.add_message(session_id, "user", req.question, req.mode.value)
        message_id = str(uuid.uuid4())
        yield {"type": "session", "session_id": session_id, "message_id": message_id}

        queue: asyncio.Queue[Any] = asyncio.Queue()
        recorder = RunRecorder(mode=req.mode, emit=queue.put_nowait)
        if req.mode == Mode.AGENT:
            recorder.available_tools = [t.value for t in req.enabled_tools]
        options = resolve_options(req, self.c.runtime)
        recorder.model = options.model
        ctx = ModeContext(
            container=self.c,
            request=req,
            options=options,
            recorder=recorder,
            history=history if req.mode in (Mode.DIRECT, Mode.AGENT) else [],
        )
        log.info("chat start mode=%s question=%s", req.mode.value, redact(req.question))

        error: AppError | None = None

        async def _runner() -> None:
            nonlocal error
            try:
                runner = MODE_RUNNERS[req.mode]
                if req.mode == Mode.AGENT:
                    async with asyncio.timeout(self.c.settings.agent_request_timeout_s):
                        await runner(ctx)
                else:
                    await runner(ctx)
            except TimeoutError:
                error = AppError(
                    f"The request exceeded the overall time limit of {self.c.settings.agent_request_timeout_s:g}s.",
                    code="request_timeout",
                )
            except AppError as exc:
                error = exc
            except Exception:  # noqa: BLE001
                log.exception("chat failed mode=%s", req.mode.value)
                error = AppError("An unexpected error occurred while processing the request.", code="internal_error")
            finally:
                queue.put_nowait(_DONE)

        task = asyncio.create_task(_runner())
        cancelled = False
        try:
            while True:
                event = await queue.get()
                if event is _DONE:
                    break
                yield event
        except (asyncio.CancelledError, GeneratorExit):
            cancelled = True
            task.cancel()
            raise
        finally:
            if cancelled:
                recorder.status = "cancelled"
                recorder.answer = recorder.answer or "(generation stopped)"
                self._persist(persist, session_id, message_id, recorder, started)

        await task
        if error is not None:
            recorder.status = "error" if not recorder.answer else "partial"
            recorder.add_error(error.code, error.message)
            response = self._persist(persist, session_id, message_id, recorder, started)
            payload = error.to_dict()
            yield {"type": "error", "error": payload, "response": response.model_dump(mode="json")}
            return
        if recorder.status == "success" and any(s.status in ("error", "timeout") for s in recorder.steps):
            recorder.status = "partial"
        response = self._persist(persist, session_id, message_id, recorder, started)
        log.info("chat done mode=%s status=%s ms=%s", req.mode.value, response.status, response.latency_ms)
        yield {"type": "done", "response": response.model_dump(mode="json")}

    def _build_response(
        self, session_id: str | None, message_id: str, rec: RunRecorder, started: float
    ) -> ChatResponse:
        return ChatResponse(
            session_id=session_id,
            message_id=message_id if session_id else None,
            mode=rec.mode,
            status=rec.status,  # type: ignore[arg-type]
            answer=rec.answer,
            model=rec.model,
            embedding_model=rec.embedding_model,
            available_tools=rec.available_tools,
            selected_tools=rec.selected_tools,
            executed_tools=rec.executed_tools,
            steps=rec.steps,
            sources=rec.sources,
            counts=rec.counts,
            citations=rec.citations,
            token_usage=rec.tokens,
            latency_ms=int((time.perf_counter() - started) * 1000),
            errors=rec.errors,
            warnings=rec.warnings,
            created_at=datetime.now(UTC),
        )

    def _persist(
        self, persist: bool, session_id: str | None, message_id: str, rec: RunRecorder, started: float
    ) -> ChatResponse:
        response = self._build_response(session_id, message_id, rec, started)
        if persist and session_id:
            meta = response.model_dump(mode="json", exclude={"answer", "session_id", "message_id"})
            try:
                self.c.sessions_repo.add_message(
                    session_id,
                    "assistant",
                    response.answer or "",
                    rec.mode.value,
                    status=response.status,
                    meta=meta,
                    message_id=message_id,
                )
            except Exception:  # noqa: BLE001
                log.exception("failed to persist assistant message")
        return response

    async def execute(self, req: ChatRequest, *, persist: bool = True) -> ChatResponse:
        """Non-streaming variant: run to completion and return the final response."""
        final: dict[str, Any] | None = None
        async for event in self.stream(req, persist=persist):
            if event["type"] in ("done", "error"):
                final = event
        assert final is not None
        if final["type"] == "error" and not final["response"].get("answer"):
            err = final["error"]
            exc = AppError(err["message"], hint=err.get("hint"), code=err["code"])
            exc.status_code = _status_for(err["code"])
            exc.retryable = bool(err.get("retryable", False))
            raise exc
        return ChatResponse.model_validate(final["response"])


def _status_for(code: str) -> int:
    from app.core import errors as e

    for cls in (
        e.LLMUnavailable,
        e.LLMTimeout,
        e.LLMModelNotFound,
        e.LLMError,
        e.EmbeddingUnavailable,
        e.SearchUnavailable,
        e.SearchRateLimited,
        e.ToolTimeout,
        e.ValidationFailed,
    ):
        if cls.code == code:
            return cls.status_code
    return 500 if code in ("internal_error",) else 502
