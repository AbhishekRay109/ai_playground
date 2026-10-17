"""Persistence for document metadata and chunk text."""

from __future__ import annotations

from sqlalchemy import func, select

from app.models.db import Database
from app.models.entities import Chunk, Document


class DocumentRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, document_id: str) -> Document | None:
        with self.db.session() as s:
            return s.get(Document, document_id)

    def get_by_hash(self, content_hash: str) -> Document | None:
        with self.db.session() as s:
            return s.scalar(select(Document).where(Document.content_hash == content_hash))

    def list(self) -> list[Document]:
        with self.db.session() as s:
            return list(s.scalars(select(Document).order_by(Document.created_at.desc())))

    def count(self) -> int:
        with self.db.session() as s:
            return int(s.scalar(select(func.count()).select_from(Document)) or 0)

    def add(self, document: Document, chunks: list[Chunk]) -> None:
        with self.db.session() as s:
            s.add(document)
            s.add_all(chunks)

    def delete(self, document_id: str) -> bool:
        with self.db.session() as s:
            doc = s.get(Document, document_id)
            if doc is None:
                return False
            s.delete(doc)
            return True

    def chunks(self, document_id: str) -> list[Chunk]:
        with self.db.session() as s:
            return list(s.scalars(select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.chunk_index)))

    def chunks_for_documents(self, document_ids: list[str] | None = None) -> list[Chunk]:
        with self.db.session() as s:
            q = select(Chunk)
            if document_ids:
                q = q.where(Chunk.document_id.in_(document_ids))
            return list(s.scalars(q))

    def set_embedding_model(self, document_id: str, model: str) -> None:
        with self.db.session() as s:
            doc = s.get(Document, document_id)
            if doc:
                doc.embedding_model = model
