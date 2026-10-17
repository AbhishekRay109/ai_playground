"""Conversation sessions."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_container
from app.core.container import Container
from app.core.errors import NotFound
from app.schemas.common import MessageOut, SessionDetail, SessionSummary

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionSummary])
async def list_sessions(c: Container = Depends(get_container)) -> list[SessionSummary]:
    return [
        SessionSummary(
            id=s.id,
            title=s.title,
            last_mode=s.last_mode,
            message_count=n,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s, n in c.sessions_repo.list()
    ]


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str, c: Container = Depends(get_container)) -> SessionDetail:
    s = c.sessions_repo.get_with_messages(session_id)
    if s is None:
        raise NotFound("Session not found.")
    messages = [
        MessageOut(
            id=m.id,
            role=m.role,
            content=m.content,
            mode=m.mode,
            status=m.status,
            meta=m.meta,
            feedback=m.feedback.rating if m.feedback else None,
            created_at=m.created_at,
        )
        for m in s.messages
    ]
    return SessionDetail(
        id=s.id,
        title=s.title,
        last_mode=s.last_mode,
        message_count=len(messages),
        created_at=s.created_at,
        updated_at=s.updated_at,
        messages=messages,
    )


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, c: Container = Depends(get_container)) -> None:
    """Delete a session with all of its messages, execution metadata and feedback."""
    if not c.sessions_repo.delete(session_id):
        raise NotFound("Session not found.")
