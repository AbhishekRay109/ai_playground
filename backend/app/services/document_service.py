"""Document ingestion pipeline: validate → hash/dedupe → extract → normalise → chunk →
embed → store vectors (Qdrant) → store metadata (SQLite)."""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from datetime import UTC, datetime

from app.core.config import Settings
from app.core.errors import AppError, NotFound, PayloadTooLarge, ValidationFailed
from app.core.logging import get_logger
from app.models.entities import Chunk, Document
from app.repositories.documents import DocumentRepository
from app.schemas.common import DocumentOut, IngestResult
from app.services import text_processing as tp
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStore, collection_name

log = get_logger(__name__)


class DocumentService:
    def __init__(
        self, settings: Settings, repo: DocumentRepository, embeddings: EmbeddingService, vectors: VectorStore
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.embeddings = embeddings
        self.vectors = vectors
        self._ingest_lock = asyncio.Lock()

    # ------------------------------------------------------------------ queries
    def list_documents(self) -> list[DocumentOut]:
        current = self.embeddings.model_name
        return [self._to_out(d, current) for d in self.repo.list()]

    @staticmethod
    def _to_out(doc: Document, current_model: str) -> DocumentOut:
        return DocumentOut(
            id=doc.id,
            filename=doc.filename,
            content_type=doc.content_type,
            size_bytes=doc.size_bytes,
            content_hash=doc.content_hash,
            page_count=doc.page_count,
            chunk_count=doc.chunk_count,
            char_count=doc.char_count,
            embedding_model=doc.embedding_model,
            status=doc.status,
            stale=doc.embedding_model != current_model,
            created_at=doc.created_at,
        )

    # ---------------------------------------------------------------- ingestion
    def validate_batch(self, files: list[tuple[str, int]]) -> None:
        if not files:
            raise ValidationFailed("No files were uploaded.")
        if len(files) > self.settings.max_files_per_upload:
            raise ValidationFailed(
                f"Too many files: {len(files)} (limit {self.settings.max_files_per_upload} per upload)."
            )
        if self.repo.count() + len(files) > self.settings.max_documents:
            raise ValidationFailed(f"Document limit reached ({self.settings.max_documents}). Delete documents first.")

    async def ingest(self, filename: str, data: bytes) -> IngestResult:
        start = time.perf_counter()
        filename = tp.sanitize_filename(filename)
        try:
            async with self._ingest_lock:  # Qdrant local mode + dedupe check need serialisation
                result = await self._ingest(filename, data)
        except AppError as exc:
            result = IngestResult(filename=filename, status="error", error=exc.message)
        except Exception:  # noqa: BLE001
            log.exception("ingestion failed file_type=%s", filename.rsplit(".", 1)[-1])
            result = IngestResult(filename=filename, status="error", error="Unexpected error while processing file.")
        result.latency_ms = int((time.perf_counter() - start) * 1000)
        log.info("ingest status=%s chunks=%s ms=%s", result.status, result.chunk_count, result.latency_ms)
        return result

    async def _ingest(self, filename: str, data: bytes) -> IngestResult:
        # 1. validate type and size
        if len(data) == 0:
            raise ValidationFailed(f"'{filename}' is empty.")
        if len(data) > self.settings.max_upload_bytes:
            raise PayloadTooLarge(f"'{filename}' exceeds the {self.settings.max_upload_mb:g} MB limit.")
        kind = tp.detect_type(filename, data)

        # 2. duplicate detection by content hash
        content_hash = hashlib.sha256(data).hexdigest()
        existing = self.repo.get_by_hash(content_hash)
        if existing:
            return IngestResult(
                filename=filename,
                status="duplicate",
                document_id=existing.id,
                duplicate_of=existing.id,
                chunk_count=existing.chunk_count,
                page_count=existing.page_count,
            )

        # 3-5. id, extraction, normalisation (CPU bound → worker thread)
        document_id = str(uuid.uuid4())
        pages = await asyncio.to_thread(tp.extract, kind, data, self.settings.max_pdf_pages)
        pages = [tp.PageText(p.page, tp.normalize_text(p.text)) for p in pages]
        total_chars = sum(len(p.text) for p in pages)
        if total_chars == 0:
            raise ValidationFailed(
                f"No extractable text found in '{filename}'. Scanned PDFs need OCR, which is not supported."
            )
        if total_chars > self.settings.max_extracted_chars:
            raise ValidationFailed(
                f"'{filename}' contains {total_chars:,} characters; the limit is {self.settings.max_extracted_chars:,}."
            )

        # 6. chunking
        chunks = tp.chunk_pages(pages, self.settings.chunk_size, self.settings.chunk_overlap)

        # 7. embeddings
        embedder = self.embeddings.get()
        vectors = await asyncio.to_thread(embedder.embed_documents, [c.text for c in chunks])
        dimension = len(vectors[0])
        coll = collection_name(self.settings.qdrant_collection_prefix, embedder.model_name, dimension)

        # 8. vectors + metadata
        now = datetime.now(UTC)
        chunk_ids = [str(uuid.uuid4()) for _ in chunks]
        payloads = [
            {
                "document_id": document_id,
                "chunk_id": cid,
                "chunk_index": c.index,
                "page": c.page,
                "filename": filename,
                "text": c.text,
                "embedding_model": embedder.model_name,
                "content_hash": content_hash,
                "uploaded_at": now.isoformat(),
            }
            for cid, c in zip(chunk_ids, chunks, strict=True)
        ]
        await asyncio.to_thread(self.vectors.ensure_collection, coll, dimension)
        await asyncio.to_thread(self.vectors.upsert, coll, chunk_ids, vectors, payloads)

        # 9. metadata in SQLite (roll back vectors if this fails)
        doc = Document(
            id=document_id,
            filename=filename,
            content_type=kind,
            size_bytes=len(data),
            content_hash=content_hash,
            page_count=len(pages) if kind == "pdf" else None,
            chunk_count=len(chunks),
            char_count=total_chars,
            embedding_model=embedder.model_name,
            status="ready",
            created_at=now,
        )
        rows = [
            Chunk(
                id=cid,
                document_id=document_id,
                chunk_index=c.index,
                page=c.page,
                text=c.text,
                char_start=c.char_start,
                char_end=c.char_end,
            )
            for cid, c in zip(chunk_ids, chunks, strict=True)
        ]
        try:
            self.repo.add(doc, rows)
        except Exception:
            await asyncio.to_thread(self.vectors.delete_document, document_id)
            raise
        return IngestResult(
            filename=filename,
            status="ready",
            document_id=document_id,
            chunk_count=len(chunks),
            page_count=doc.page_count,
        )

    # ----------------------------------------------------------------- deletion
    async def delete(self, document_id: str) -> None:
        if self.repo.get(document_id) is None:
            raise NotFound("Document not found.")
        async with self._ingest_lock:
            await asyncio.to_thread(self.vectors.delete_document, document_id)
            self.repo.delete(document_id)

    # ---------------------------------------------------------------- reindex
    async def reindex(self, document_id: str) -> DocumentOut:
        """Re-embed stored chunk text with the current embedding model."""
        doc = self.repo.get(document_id)
        if doc is None:
            raise NotFound("Document not found.")
        chunks = self.repo.chunks(document_id)
        embedder = self.embeddings.get()
        vectors = await asyncio.to_thread(embedder.embed_documents, [c.text for c in chunks])
        coll = collection_name(self.settings.qdrant_collection_prefix, embedder.model_name, len(vectors[0]))
        payloads = [
            {
                "document_id": doc.id,
                "chunk_id": c.id,
                "chunk_index": c.chunk_index,
                "page": c.page,
                "filename": doc.filename,
                "text": c.text,
                "embedding_model": embedder.model_name,
                "content_hash": doc.content_hash,
                "uploaded_at": doc.created_at.isoformat(),
            }
            for c in chunks
        ]
        async with self._ingest_lock:
            await asyncio.to_thread(self.vectors.delete_document, document_id)
            await asyncio.to_thread(self.vectors.ensure_collection, coll, len(vectors[0]))
            await asyncio.to_thread(self.vectors.upsert, coll, [c.id for c in chunks], vectors, payloads)
            self.repo.set_embedding_model(document_id, embedder.model_name)
        return self._to_out(self.repo.get(document_id), self.embeddings.model_name)  # type: ignore[arg-type]
