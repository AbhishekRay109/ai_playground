"""Application configuration.

All settings come from environment variables (optionally a ``.env`` file). Values that a
user may change at runtime from the Settings panel (chat model, temperature, ...) live in
:class:`app.services.settings_service.RuntimeSettings` and are persisted in SQLite; the
values here are their defaults.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Lists may be given as comma-separated strings in the environment.
StrList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    # `.env` in the working directory wins over the repository-root `.env` used by Docker Compose.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore")

    # --- application ---------------------------------------------------------------
    app_name: str = "Open-Source AI Playground"
    environment: Literal["development", "test", "production"] = "development"
    data_dir: Path = Path("./data")
    database_url: str | None = None  # defaults to sqlite:///<data_dir>/app.db
    demo_db_path: Path | None = None  # defaults to <data_dir>/demo.db
    log_level: str = "INFO"
    # Logging of prompts / document text is off by default (privacy).
    log_content: bool = False

    # --- HTTP / security -------------------------------------------------------------
    cors_origins: StrList = Field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])
    max_request_bytes: int = 256 * 1024  # JSON bodies
    rate_limit_per_minute: int = 60  # per client IP, for expensive POST endpoints; 0 disables
    max_question_chars: int = 4000

    # --- LLM (Ollama) ----------------------------------------------------------------
    ollama_base_url: str = "http://localhost:11434"
    # Apache-2.0 licensed default; any installed instruction model can be selected at runtime.
    ollama_model: str = "qwen2.5:7b"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 1024
    llm_timeout_s: float = 120.0
    llm_history_messages: int = 10  # previous messages sent to the model in Direct/Agent mode

    # --- embeddings / vectors -------------------------------------------------------
    embedding_provider: Literal["sentence-transformers", "hash"] = "sentence-transformers"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_device: str = "cpu"
    # sentence-transformers downloads weights on first use. Off by default so nothing is
    # downloaded without an explicit action (see `python -m app.cli download-embedding-model`).
    embedding_allow_download: bool = False
    embedding_batch_size: int = 32
    reranker_model: str | None = None  # e.g. cross-encoder/ms-marco-MiniLM-L-6-v2
    qdrant_path: Path | None = None  # defaults to <data_dir>/qdrant (local mode)
    qdrant_url: str | None = None  # set to use a Qdrant server instead of local mode
    qdrant_collection_prefix: str = "documents"

    # --- document ingestion -----------------------------------------------------------
    max_upload_mb: float = 20.0
    max_files_per_upload: int = 5
    max_documents: int = 200
    max_pdf_pages: int = 500
    max_extracted_chars: int = 2_000_000
    chunk_size: int = 1000
    chunk_overlap: int = 150

    # --- retrieval --------------------------------------------------------------------
    rag_top_k: int = 5
    rag_score_threshold: float = 0.3
    evidence_max_chars: int = 12_000

    # --- web search -------------------------------------------------------------------
    searxng_url: str = "http://localhost:8080"
    search_timeout_s: float = 10.0
    search_results: int = 5
    web_fetch_pages: int = 3
    web_fetch_timeout_s: float = 8.0
    web_max_page_bytes: int = 2 * 1024 * 1024
    web_max_chars_per_page: int = 4000
    web_max_redirects: int = 4
    web_respect_robots: bool = True
    web_allow_private_networks: bool = False  # never enable on a shared host
    web_allowed_domains: StrList = Field(default_factory=list)  # empty = all public domains
    web_blocked_domains: StrList = Field(default_factory=list)
    web_user_agent: str = "OpenSourceAIPlayground/0.1 (+local demo; respects robots.txt)"

    # --- SQL assistant ----------------------------------------------------------------
    sql_row_limit: int = 200
    sql_timeout_s: float = 3.0
    sql_allowed_tables: StrList = Field(
        default_factory=lambda: ["customers", "products", "orders", "order_items", "monthly_sales"]
    )

    # --- agent -------------------------------------------------------------------------
    agent_max_iterations: int = 6
    agent_max_tool_calls: int = 4
    agent_tool_timeout_s: float = 45.0
    agent_request_timeout_s: float = 240.0
    tool_output_max_chars: int = 6000

    @field_validator("cors_origins", "web_allowed_domains", "web_blocked_domains", "sql_allowed_tables", mode="before")
    @classmethod
    def _split_csv(cls, v):  # noqa: ANN001
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                import json

                return json.loads(v)
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @field_validator("chunk_overlap")
    @classmethod
    def _overlap_lt_size(cls, v: int, info):  # noqa: ANN001
        size = info.data.get("chunk_size", 1000)
        if v < 0 or v >= size:
            raise ValueError("chunk_overlap must be >= 0 and smaller than chunk_size")
        return v

    # --- derived paths ---------------------------------------------------------------
    @property
    def resolved_database_url(self) -> str:
        return self.database_url or f"sqlite:///{(self.data_dir / 'app.db').as_posix()}"

    @property
    def resolved_demo_db_path(self) -> Path:
        return self.demo_db_path or self.data_dir / "demo.db"

    @property
    def resolved_qdrant_path(self) -> Path:
        return self.qdrant_path or self.data_dir / "qdrant"

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)


@lru_cache
def get_settings() -> Settings:
    return Settings()
