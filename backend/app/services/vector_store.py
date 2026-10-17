"""Qdrant vector storage (local mode by default, server mode when QDRANT_URL is set).

One collection is created per embedding model (vectors from different models are not
comparable). Point ids equal the chunk ids stored in SQLite.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient, models

from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class VectorHit:
    id: str
    score: float
    payload: dict[str, Any]


def collection_name(prefix: str, model_name: str, dimension: int) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", model_name).strip("_").lower()[:80]
    return f"{prefix}__{slug}__{dimension}"


class VectorStore:
    def __init__(
        self,
        *,
        path: Path | None = None,
        url: str | None = None,
        prefix: str = "documents",
        client: QdrantClient | None = None,
    ) -> None:
        self.prefix = prefix
        if client is not None:
            self.client = client
            self.description = "qdrant (injected)"
        elif url:
            self.client = QdrantClient(url=url, timeout=10)
            self.description = f"qdrant server ({url})"
        else:
            assert path is not None
            path.mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=str(path))
            self.description = f"qdrant local mode ({path})"
        # Local mode is not safe for concurrent writers; serialize access.
        self._lock = threading.RLock()

    def ensure_collection(self, name: str, dimension: int) -> None:
        with self._lock:
            if not self.client.collection_exists(name):
                self.client.create_collection(
                    name, vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE)
                )

    def upsert(self, name: str, ids: list[str], vectors: list[list[float]], payloads: list[dict]) -> None:
        with self._lock:
            self.client.upsert(
                name,
                points=[
                    models.PointStruct(id=i, vector=v, payload=p)
                    for i, v, p in zip(ids, vectors, payloads, strict=True)
                ],
                wait=True,
            )

    def search(
        self,
        name: str,
        vector: list[float],
        limit: int,
        score_threshold: float | None = None,
        document_ids: list[str] | None = None,
    ) -> list[VectorHit]:
        with self._lock:
            if not self.client.collection_exists(name):
                return []
            query_filter = None
            if document_ids:
                query_filter = models.Filter(
                    must=[models.FieldCondition(key="document_id", match=models.MatchAny(any=document_ids))]
                )
            resp = self.client.query_points(
                name,
                query=vector,
                limit=limit,
                score_threshold=score_threshold,
                query_filter=query_filter,
                with_payload=True,
            )
        return [VectorHit(id=str(p.id), score=float(p.score), payload=p.payload or {}) for p in resp.points]

    def _own_collections(self) -> list[str]:
        return [c.name for c in self.client.get_collections().collections if c.name.startswith(self.prefix + "__")]

    def delete_document(self, document_id: str) -> None:
        selector = models.FilterSelector(
            filter=models.Filter(
                must=[models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id))]
            )
        )
        with self._lock:
            for name in self._own_collections():
                self.client.delete(name, points_selector=selector, wait=True)

    def count(self, name: str, document_id: str | None = None) -> int:
        with self._lock:
            if not self.client.collection_exists(name):
                return 0
            flt = None
            if document_id:
                flt = models.Filter(
                    must=[models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id))]
                )
            return self.client.count(name, count_filter=flt, exact=True).count

    def health(self) -> tuple[bool, str]:
        try:
            with self._lock:
                n = len(self._own_collections())
            return True, f"{self.description}, {n} collection(s)"
        except Exception as exc:  # noqa: BLE001
            return False, f"{self.description}: {type(exc).__name__}"

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:  # noqa: BLE001
            pass
