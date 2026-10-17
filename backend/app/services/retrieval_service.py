"""Query-time retrieval: embed the question, search Qdrant, threshold, optional rerank."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from app.core.config import Settings
from app.core.logging import get_logger
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStore, collection_name

log = get_logger(__name__)


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    filename: str
    page: int | None
    chunk_index: int
    text: str
    score: float
    rerank_score: float | None = None


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk]
    embedding_model: str
    top_k: int
    score_threshold: float
    candidates: int  # hits before thresholding
    reranked: bool = False
    latency_ms: int = 0
    notes: list[str] = field(default_factory=list)


class RetrievalService:
    def __init__(self, settings: Settings, embeddings: EmbeddingService, vectors: VectorStore) -> None:
        self.settings = settings
        self.embeddings = embeddings
        self.vectors = vectors

    async def retrieve(
        self, query: str, top_k: int, score_threshold: float, document_ids: list[str] | None = None
    ) -> RetrievalResult:
        start = time.perf_counter()
        embedder = self.embeddings.get()
        vector = await asyncio.to_thread(embedder.embed_query, query)
        coll = collection_name(self.settings.qdrant_collection_prefix, embedder.model_name, len(vector))
        reranker = self.embeddings.reranker
        fetch_k = top_k * 3 if reranker else top_k
        # Fetch without threshold first so we can report how many candidates were filtered.
        hits = await asyncio.to_thread(self.vectors.search, coll, vector, fetch_k, None, document_ids)
        kept = [h for h in hits if h.score >= score_threshold]
        chunks = [
            RetrievedChunk(
                chunk_id=str(h.payload.get("chunk_id", h.id)),
                document_id=h.payload.get("document_id", ""),
                filename=h.payload.get("filename", "unknown"),
                page=h.payload.get("page"),
                chunk_index=int(h.payload.get("chunk_index", 0)),
                text=h.payload.get("text", ""),
                score=h.score,
            )
            for h in kept
        ]
        notes: list[str] = []
        reranked = False
        if reranker and chunks:
            scores = await asyncio.to_thread(reranker.rerank, query, [c.text for c in chunks])
            for c, s in zip(chunks, scores, strict=True):
                c.rerank_score = s
            chunks.sort(key=lambda c: c.rerank_score or 0.0, reverse=True)
            reranked = True
            notes.append(f"Reranked with {reranker.model_name}")
        chunks = chunks[:top_k]
        if hits and not kept:
            notes.append(
                f"{len(hits)} candidate(s) found but none reached the similarity threshold {score_threshold:.2f}"
            )
        return RetrievalResult(
            chunks=chunks,
            embedding_model=embedder.model_name,
            top_k=top_k,
            score_threshold=score_threshold,
            candidates=len(hits),
            reranked=reranked,
            latency_ms=int((time.perf_counter() - start) * 1000),
            notes=notes,
        )
