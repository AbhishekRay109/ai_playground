"""Request/response schemas shared by every execution mode."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class Mode(StrEnum):
    DOCUMENT_RAG = "document_rag"
    WEB_SEARCH = "web_search"
    SQL = "sql"
    AGENT = "agent"
    DIRECT = "direct"


class ToolName(StrEnum):
    DOCUMENT_RETRIEVAL = "document_retrieval"
    WEB_SEARCH = "web_search"
    SQL_QUERY = "sql_query"
    CALCULATOR = "calculator"


class RequestSettings(BaseModel):
    """Optional per-request overrides. Unset fields use the runtime settings."""

    model: str | None = Field(default=None, max_length=200)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=16, le=8192)
    top_k: int | None = Field(default=None, ge=1, le=20)
    score_threshold: float | None = Field(default=None, ge=-1.0, le=1.0)
    search_results: int | None = Field(default=None, ge=1, le=10)
    document_ids: list[str] | None = Field(default=None, max_length=100)


class ChatRequest(BaseModel):
    session_id: str | None = Field(default=None, max_length=36)
    question: str = Field(min_length=1)
    mode: Mode
    enabled_tools: list[ToolName] = Field(default_factory=list)
    settings: RequestSettings = Field(default_factory=RequestSettings)

    @field_validator("question")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("question must not be blank")
        return v

    @field_validator("enabled_tools")
    @classmethod
    def _dedupe(cls, v: list[ToolName]) -> list[ToolName]:
        return list(dict.fromkeys(v))


StepStatus = Literal["running", "success", "error", "timeout", "rejected", "skipped"]


class ExecutionStep(BaseModel):
    id: str
    kind: Literal["tool", "llm", "system"]
    name: str  # tool name or "llm" / "retrieval" etc.
    status: StepStatus
    purpose: str | None = None
    input_summary: str | None = None
    result_summary: str | None = None
    latency_ms: int | None = None
    retries: int = 0
    details: dict[str, Any] = Field(default_factory=dict)


class Source(BaseModel):
    id: int  # citation number used in the answer, e.g. [1]
    kind: Literal["document", "web", "sql"]
    title: str
    excerpt: str
    cited: bool = False
    # document sources
    document_id: str | None = None
    filename: str | None = None
    page: int | None = None
    chunk_id: str | None = None
    chunk_index: int | None = None
    score: float | None = None
    # web sources
    url: str | None = None
    content_type: Literal["page", "snippet"] | None = None
    engine: str | None = None
    published_date: str | None = None
    # sql sources
    sql: str | None = None
    row_count: int | None = None


class Counts(BaseModel):
    retrieved_chunks: int = 0
    web_sources: int = 0
    sql_rows: int = 0
    tool_calls: int = 0


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # True when counts are approximated (chars / 4) because the model did not report them.
    estimated: bool = False


class CitationReport(BaseModel):
    total_markers: int = 0
    valid_markers: int = 0
    invalid_markers: list[int] = Field(default_factory=list)


class ChatResponse(BaseModel):
    session_id: str | None
    message_id: str | None
    mode: Mode
    status: Literal["success", "partial", "error", "cancelled"]
    answer: str
    model: str | None = None
    embedding_model: str | None = None
    available_tools: list[str] = Field(default_factory=list)
    selected_tools: list[str] = Field(default_factory=list)  # tools the agent asked for
    executed_tools: list[str] = Field(default_factory=list)  # tools that actually ran
    steps: list[ExecutionStep] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    counts: Counts = Field(default_factory=Counts)
    citations: CitationReport = Field(default_factory=CitationReport)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    latency_ms: int = 0
    errors: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


class FeedbackRequest(BaseModel):
    rating: Literal[1, -1]
    comment: str | None = Field(default=None, max_length=2000)
