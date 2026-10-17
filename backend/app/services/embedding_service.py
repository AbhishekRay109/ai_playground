"""Local text embeddings.

``sentence-transformers`` is the default provider. A deterministic feature-hashing embedder
(``hash``) exists for unit tests and fully offline demos; it is lexical only and must be
selected explicitly with ``EMBEDDING_PROVIDER=hash``. It is never used as a silent fallback.
"""

from __future__ import annotations

import hashlib
import math
import re
import threading
from typing import Protocol

from app.core.errors import EmbeddingUnavailable
from app.core.logging import get_logger

log = get_logger(__name__)


class Embedder(Protocol):
    model_name: str

    @property
    def dimension(self) -> int: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "a an and are as at be by for from has have how i in is it of on or that the this to was "
    "what when where which who why will with does do did my our your their".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


class HashingEmbedder:
    """Signed feature hashing of unigrams and bigrams, L2-normalised. Deterministic."""

    def __init__(self, dimension: int = 384) -> None:
        self._dim = dimension
        self.model_name = f"hash-{dimension}"

    @property
    def dimension(self) -> int:
        return self._dim

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        tokens = tokenize(text)
        features = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:], strict=False)]
        for feat in features:
            digest = hashlib.md5(feat.encode("utf-8"), usedforsecurity=False).digest()
            idx = int.from_bytes(digest[:4], "little") % self._dim
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class SentenceTransformerEmbedder:
    def __init__(
        self, model_name: str, device: str = "cpu", allow_download: bool = False, batch_size: int = 32
    ) -> None:
        self.model_name = model_name
        self._device = device
        self._allow_download = allow_download
        self._batch_size = batch_size
        self._model = None
        self._lock = threading.Lock()

    def _load(self):  # noqa: ANN202
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise EmbeddingUnavailable(
                    "sentence-transformers is not installed.",
                    hint='Install it with `pip install -e ".[embeddings]"` in the backend directory.',
                ) from exc
            try:
                self._model = SentenceTransformer(
                    self.model_name, device=self._device, local_files_only=not self._allow_download
                )
            except Exception as exc:  # noqa: BLE001 - library raises many types
                log.warning("embedding model load failed model=%s error=%s", self.model_name, type(exc).__name__)
                raise EmbeddingUnavailable(
                    f"Embedding model '{self.model_name}' is not available locally.",
                    hint=(
                        "Download it once with `python -m app.cli download-embedding-model` "
                        "(or set EMBEDDING_ALLOW_DOWNLOAD=true)."
                    ),
                ) from exc
            return self._model

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def dimension(self) -> int:
        model = self._load()
        getter = getattr(model, "get_sentence_embedding_dimension", None)
        return int(getter()) if getter else len(self.embed_query("dimension probe"))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        vectors = model.encode(texts, batch_size=self._batch_size, normalize_embeddings=True, show_progress_bar=False)
        return [v.tolist() for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class Reranker(Protocol):
    model_name: str

    def rerank(self, query: str, texts: list[str]) -> list[float]: ...


class CrossEncoderReranker:
    """Optional local reranker (sentence-transformers ``CrossEncoder``)."""

    def __init__(self, model_name: str, allow_download: bool = False) -> None:
        self.model_name = model_name
        self._allow_download = allow_download
        self._model = None

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder

                self._model = CrossEncoder(self.model_name, local_files_only=not self._allow_download)
            except Exception as exc:  # noqa: BLE001
                raise EmbeddingUnavailable(
                    f"Reranker '{self.model_name}' is not available locally.",
                    hint="Unset RERANKER_MODEL or download the model first.",
                ) from exc
        scores = self._model.predict([(query, t) for t in texts])
        return [float(s) for s in scores]


class EmbeddingService:
    """Holds the active embedder; switching models creates a new embedder lazily."""

    def __init__(
        self,
        provider: str,
        model_name: str,
        device: str = "cpu",
        allow_download: bool = False,
        batch_size: int = 32,
        reranker_model: str | None = None,
    ) -> None:
        self.provider = provider
        self._device = device
        self._allow_download = allow_download
        self._batch_size = batch_size
        self._embedders: dict[str, Embedder] = {}
        self.model_name = model_name
        self.reranker: Reranker | None = (
            CrossEncoderReranker(reranker_model, allow_download) if reranker_model else None
        )

    def set_model(self, model_name: str) -> None:
        self.model_name = model_name

    def get(self, model_name: str | None = None) -> Embedder:
        name = model_name or self.model_name
        if name not in self._embedders:
            if self.provider == "hash":
                dim = int(name.split("-")[-1]) if name.startswith("hash-") and name.split("-")[-1].isdigit() else 384
                self._embedders[name] = HashingEmbedder(dim)
            else:
                self._embedders[name] = SentenceTransformerEmbedder(
                    name, self._device, self._allow_download, self._batch_size
                )
        return self._embedders[name]

    @property
    def active_model_name(self) -> str:
        return self.get().model_name

    def is_loaded(self) -> bool:
        emb = self._embedders.get(self.model_name)
        return isinstance(emb, HashingEmbedder) or bool(getattr(emb, "loaded", False))
