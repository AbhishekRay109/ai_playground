"""Schemas for documents, sessions, models, health and configuration endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class DocumentOut(BaseModel):
    id: str
    filename: str
    content_type: str
    size_bytes: int
    content_hash: str
    page_count: int | None
    chunk_count: int
    char_count: int
    embedding_model: str
    status: str
    stale: bool = False  # embedded with a different model than the current one
    created_at: datetime


class IngestResult(BaseModel):
    filename: str
    status: Literal["ready", "duplicate", "error"]
    document_id: str | None = None
    chunk_count: int = 0
    page_count: int | None = None
    duplicate_of: str | None = None
    error: str | None = None
    latency_ms: int = 0


class UploadResponse(BaseModel):
    results: list[IngestResult]


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    mode: str | None
    status: str
    meta: dict[str, Any] | None = None
    feedback: int | None = None
    created_at: datetime


class SessionSummary(BaseModel):
    id: str
    title: str
    last_mode: str | None
    message_count: int
    created_at: datetime
    updated_at: datetime


class SessionDetail(SessionSummary):
    messages: list[MessageOut]


class ModelInfo(BaseModel):
    name: str
    size_bytes: int | None = None
    family: str | None = None
    parameter_size: str | None = None
    quantization: str | None = None
    modified_at: str | None = None


class ModelsResponse(BaseModel):
    available: bool
    models: list[ModelInfo] = Field(default_factory=list)
    current_model: str
    error: str | None = None
    hint: str | None = None


class ServiceStatus(BaseModel):
    ok: bool
    detail: str
    hint: str | None = None
    latency_ms: int | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    services: dict[str, ServiceStatus]


class RuntimeConfig(BaseModel):
    """User-adjustable settings (persisted)."""

    chat_model: str
    temperature: float = Field(ge=0.0, le=2.0)
    max_tokens: int = Field(ge=16, le=8192)
    llm_timeout_s: float = Field(ge=5, le=900)
    embedding_model: str = Field(min_length=1, max_length=200)
    rag_top_k: int = Field(ge=1, le=20)
    rag_score_threshold: float = Field(ge=-1.0, le=1.0)


class RuntimeConfigUpdate(BaseModel):
    chat_model: str | None = Field(default=None, min_length=1, max_length=200)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=16, le=8192)
    llm_timeout_s: float | None = Field(default=None, ge=5, le=900)
    embedding_model: str | None = Field(default=None, min_length=1, max_length=200)
    rag_top_k: int | None = Field(default=None, ge=1, le=20)
    rag_score_threshold: float | None = Field(default=None, ge=-1.0, le=1.0)


class ConfigResponse(BaseModel):
    """Public, non-secret configuration exposed to the UI."""

    runtime: RuntimeConfig
    embedding_provider: str
    ollama_base_url: str
    searxng_url: str
    vector_store: str
    limits: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)
