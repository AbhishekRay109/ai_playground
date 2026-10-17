"""Persistence for chat sessions, messages and feedback."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.db import Database
from app.models.entities import ChatSession, Feedback, Message, utcnow


class SessionRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get_or_create(self, session_id: str | None, title_hint: str) -> ChatSession:
        with self.db.session() as s:
            if session_id:
                existing = s.get(ChatSession, session_id)
                if existing:
                    return existing
            title = " ".join(title_hint.split())[:80] or "New chat"
            obj = ChatSession(id=session_id or str(uuid.uuid4()), title=title)
            s.add(obj)
            return obj

    def exists(self, session_id: str) -> bool:
        with self.db.session() as s:
            return s.get(ChatSession, session_id) is not None

    def list(self, limit: int = 100) -> list[tuple[ChatSession, int]]:
        with self.db.session() as s:
            counts = (
                select(Message.session_id, func.count(Message.id).label("n")).group_by(Message.session_id).subquery()
            )
            rows = s.execute(
                select(ChatSession, func.coalesce(counts.c.n, 0))
                .outerjoin(counts, counts.c.session_id == ChatSession.id)
                .order_by(ChatSession.updated_at.desc())
                .limit(limit)
            ).all()
            return [(r[0], int(r[1])) for r in rows]

    def get_with_messages(self, session_id: str) -> ChatSession | None:
        with self.db.session() as s:
            return s.scalar(
                select(ChatSession)
                .where(ChatSession.id == session_id)
                .options(selectinload(ChatSession.messages).selectinload(Message.feedback))
            )

    def delete(self, session_id: str) -> bool:
        with self.db.session() as s:
            obj = s.get(ChatSession, session_id)
            if obj is None:
                return False
            s.delete(obj)
            return True

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        mode: str | None,
        status: str = "success",
        meta: dict[str, Any] | None = None,
        message_id: str | None = None,
    ) -> Message:
        with self.db.session() as s:
            msg = Message(
                id=message_id or str(uuid.uuid4()),
                session_id=session_id,
                role=role,
                content=content,
                mode=mode,
                status=status,
                meta=meta,
                created_at=utcnow(),
            )
            s.add(msg)
            sess = s.get(ChatSession, session_id)
            if sess:
                sess.updated_at = utcnow()
                if mode:
                    sess.last_mode = mode
            return msg

    def recent_messages(self, session_id: str, limit: int) -> list[Message]:
        with self.db.session() as s:
            rows = s.scalars(
                select(Message)
                .where(Message.session_id == session_id, Message.status == "success")
                .order_by(Message.created_at.desc())
                .limit(limit)
            ).all()
            return list(reversed(rows))

    def set_feedback(self, message_id: str, rating: int, comment: str | None) -> bool:
        with self.db.session() as s:
            msg = s.get(Message, message_id)
            if msg is None or msg.role != "assistant":
                return False
            fb = s.scalar(select(Feedback).where(Feedback.message_id == message_id))
            if fb:
                fb.rating, fb.comment = rating, comment
            else:
                s.add(Feedback(message_id=message_id, rating=rating, comment=comment))
            return True
