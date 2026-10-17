"""Service container: builds and wires every service once per application instance.

Tests construct a container with fakes injected at the external boundaries (LLM client,
HTTP transports, embedder provider) instead of patching modules.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import Settings
from app.models.db import Database
from app.repositories.documents import DocumentRepository
from app.repositories.sessions import SessionRepository
from app.services.demo_db import create_demo_db
from app.services.document_service import DocumentService
from app.services.embedding_service import EmbeddingService
from app.services.llm_service import LLMClient, OllamaClient
from app.services.retrieval_service import RetrievalService
from app.services.search_service import SearchService, SearxngClient
from app.services.settings_service import SettingsService
from app.services.sql_service import SqlService
from app.services.vector_store import VectorStore
from app.services.web_fetcher import UrlPolicy, WebFetcher


@dataclass
class Container:
    settings: Settings
    db: Database
    llm: LLMClient
    embeddings: EmbeddingService
    vectors: VectorStore
    documents_repo: DocumentRepository
    sessions_repo: SessionRepository
    runtime: SettingsService
    documents: DocumentService
    retrieval: RetrievalService
    search: SearchService
    sql: SqlService

    def close(self) -> None:
        self.vectors.close()
        self.db.engine.dispose()


def build_container(
    settings: Settings,
    *,
    llm: LLMClient | None = None,
    searxng_transport: httpx.AsyncBaseTransport | None = None,
    web_transport: httpx.AsyncBaseTransport | None = None,
    vector_store: VectorStore | None = None,
) -> Container:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.resolved_database_url)
    db.create_all()
    create_demo_db(settings.resolved_demo_db_path)

    runtime = SettingsService(settings, db)
    llm_client: LLMClient = llm or OllamaClient(settings.ollama_base_url)
    embeddings = EmbeddingService(
        settings.embedding_provider,
        runtime.current.embedding_model,
        settings.embedding_device,
        settings.embedding_allow_download,
        settings.embedding_batch_size,
        settings.reranker_model,
    )
    vectors = vector_store or VectorStore(
        path=settings.resolved_qdrant_path, url=settings.qdrant_url, prefix=settings.qdrant_collection_prefix
    )
    documents_repo = DocumentRepository(db)
    policy = UrlPolicy(
        allow_private=settings.web_allow_private_networks,
        allowed_domains=tuple(settings.web_allowed_domains),
        blocked_domains=tuple(settings.web_blocked_domains),
    )
    fetcher = WebFetcher(
        policy,
        timeout_s=settings.web_fetch_timeout_s,
        max_bytes=settings.web_max_page_bytes,
        max_redirects=settings.web_max_redirects,
        user_agent=settings.web_user_agent,
        respect_robots=settings.web_respect_robots,
        transport=web_transport,
    )
    return Container(
        settings=settings,
        db=db,
        llm=llm_client,
        embeddings=embeddings,
        vectors=vectors,
        documents_repo=documents_repo,
        sessions_repo=SessionRepository(db),
        runtime=runtime,
        documents=DocumentService(settings, documents_repo, embeddings, vectors),
        retrieval=RetrievalService(settings, embeddings, vectors),
        search=SearchService(
            settings, SearxngClient(settings.searxng_url, settings.search_timeout_s, searxng_transport), fetcher
        ),
        sql=SqlService(settings, llm_client, settings.resolved_demo_db_path),
    )
