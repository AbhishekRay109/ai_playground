"""FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request

from app.core.container import Container
from app.services.chat_service import ChatService


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_chat_service(request: Request) -> ChatService:
    return request.app.state.chat_service
