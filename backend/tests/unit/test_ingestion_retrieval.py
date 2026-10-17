"""Ingestion → Qdrant (real, local mode) → retrieval, with the deterministic hash embedder."""

from app.services.vector_store import collection_name
from tests.conftest import SAMPLE_MD
from tests.unit.test_text_processing import make_pdf


async def test_ingest_stores_vectors_and_metadata(container):
    result = await container.documents.ingest("policy.md", SAMPLE_MD.encode())
    assert result.status == "ready"
    assert result.chunk_count >= 2
    doc = container.documents_repo.get(result.document_id)
    assert doc.filename == "policy.md" and doc.content_type == "md"
    assert len(doc.content_hash) == 64
    assert doc.embedding_model == "hash-384"
    chunks = container.documents_repo.chunks(result.document_id)
    assert len(chunks) == result.chunk_count
    coll = collection_name("documents", "hash-384", 384)
    assert container.vectors.count(coll, result.document_id) == result.chunk_count


async def test_duplicate_upload_detected_by_hash(container):
    first = await container.documents.ingest("a.md", SAMPLE_MD.encode())
    second = await container.documents.ingest("copy.md", SAMPLE_MD.encode())
    assert second.status == "duplicate"
    assert second.duplicate_of == first.document_id
    assert container.documents_repo.count() == 1


async def test_invalid_and_empty_uploads_return_errors(container):
    assert (await container.documents.ingest("x.exe", b"MZ")).status == "error"
    assert (await container.documents.ingest("empty.txt", b"")).status == "error"
    blank = await container.documents.ingest("blank.txt", b"   \n\n  ")
    assert blank.status == "error" and "No extractable text" in blank.error


async def test_upload_size_limit(container):
    container.settings.max_upload_mb = 0.0001
    result = await container.documents.ingest("big.txt", b"x" * 1000)
    assert result.status == "error" and "limit" in result.error


async def test_delete_removes_vectors_and_chunks(container):
    result = await container.documents.ingest("policy.md", SAMPLE_MD.encode())
    coll = collection_name("documents", "hash-384", 384)
    await container.documents.delete(result.document_id)
    assert container.documents_repo.get(result.document_id) is None
    assert container.documents_repo.chunks(result.document_id) == []
    assert container.vectors.count(coll, result.document_id) == 0


async def test_retrieval_returns_relevant_chunk_with_real_metadata(container):
    result = await container.documents.ingest("policy.md", SAMPLE_MD.encode())
    retrieved = await container.retrieval.retrieve(
        "How far in advance must international travel be booked?", top_k=3, score_threshold=0.05
    )
    assert retrieved.chunks, "expected at least one chunk"
    top = retrieved.chunks[0]
    assert "21 days" in top.text
    assert top.document_id == result.document_id
    assert top.filename == "policy.md"
    stored_ids = {c.id for c in container.documents_repo.chunks(result.document_id)}
    assert all(c.chunk_id in stored_ids for c in retrieved.chunks)


async def test_pdf_chunks_carry_page_numbers(container):
    pdf = make_pdf(["Introduction to the handbook.", "Passwords must be at least 14 characters long."])
    res = await container.documents.ingest("handbook.pdf", pdf)
    assert res.status == "ready" and res.page_count == 2
    retrieved = await container.retrieval.retrieve("password length characters", top_k=1, score_threshold=0.0)
    assert retrieved.chunks[0].page == 2


async def test_similarity_threshold_filters_everything(container):
    await container.documents.ingest("policy.md", SAMPLE_MD.encode())
    retrieved = await container.retrieval.retrieve("quantum chromodynamics gluon", top_k=3, score_threshold=0.9)
    assert retrieved.chunks == []
    assert retrieved.candidates > 0
    assert "threshold" in retrieved.notes[0]


async def test_document_filter(container):
    a = await container.documents.ingest("a.md", SAMPLE_MD.encode())
    await container.documents.ingest("b.md", b"International travel insurance covers evacuation.")
    retrieved = await container.retrieval.retrieve(
        "international travel", top_k=5, score_threshold=0.0, document_ids=[a.document_id]
    )
    assert {c.document_id for c in retrieved.chunks} == {a.document_id}


async def test_reindex_after_embedding_model_change(container):
    res = await container.documents.ingest("policy.md", SAMPLE_MD.encode())
    container.embeddings.set_model("hash-256")
    assert container.documents.list_documents()[0].stale is True
    out = await container.documents.reindex(res.document_id)
    assert out.embedding_model == "hash-256" and out.stale is False
    retrieved = await container.retrieval.retrieve("international travel booked", top_k=1, score_threshold=0.0)
    assert retrieved.chunks and retrieved.embedding_model == "hash-256"
