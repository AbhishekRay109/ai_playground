"""Chat endpoints: JSON (`POST /chat`) and Server-Sent Events (`POST /chat/stream`)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_chat_service, get_container
from app.core.container import Container
from app.core.errors import NotFound
from app.schemas.chat import ChatRequest, ChatResponse, FeedbackRequest
from app.services.chat_service import ChatService

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, service: ChatService = Depends(get_chat_service)) -> ChatResponse:
    """Run one question through the selected mode and return the complete response."""
    return await service.execute(req)


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, service: ChatService = Depends(get_chat_service)) -> StreamingResponse:
    """Stream typed events: session, status, tool_start, tool_end, sources, delta, done, error.

    Closing the connection cancels the run (used by the UI's Stop button).
    """
    events = service.stream(req)
    # Validate eagerly so request errors return a normal HTTP error rather than a stream.
    first = await events.__anext__()

    async def gen() -> AsyncIterator[bytes]:
        yield _sse(first)
        async for event in events:
            yield _sse(event)

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


def _sse(event: dict) -> bytes:
    return f"event: {event['type']}\ndata: {json.dumps(event, default=str)}\n\n".encode()


@router.post("/messages/{message_id}/feedback", status_code=204)
async def feedback(message_id: str, body: FeedbackRequest, c: Container = Depends(get_container)) -> None:
    if not c.sessions_repo.set_feedback(message_id, body.rating, body.comment):
        raise NotFound("Assistant message not found.")
