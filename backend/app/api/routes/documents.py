"""Document upload and management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile

from app.api.deps import get_container
from app.core.container import Container
from app.core.errors import PayloadTooLarge
from app.schemas.common import DocumentOut, IngestResult, UploadResponse

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", response_model=UploadResponse)
async def upload_documents(
    files: list[UploadFile] = File(...), c: Container = Depends(get_container)
) -> UploadResponse:
    """Upload PDF, DOCX, TXT or Markdown files. Each file is processed independently."""
    c.documents.validate_batch([(f.filename or "", f.size or 0) for f in files])
    results: list[IngestResult] = []
    limit = c.settings.max_upload_bytes
    for f in files:
        data = await f.read(limit + 1)
        await f.close()
        if len(data) > limit:
            results.append(
                IngestResult(
                    filename=f.filename or "untitled",
                    status="error",
                    error=PayloadTooLarge(f"File exceeds {c.settings.max_upload_mb:g} MB.").message,
                )
            )
            continue
        results.append(await c.documents.ingest(f.filename or "untitled", data))
    return UploadResponse(results=results)


@router.get("", response_model=list[DocumentOut])
async def list_documents(c: Container = Depends(get_container)) -> list[DocumentOut]:
    return c.documents.list_documents()


@router.delete("/{document_id}", status_code=204)
async def delete_document(document_id: str, c: Container = Depends(get_container)) -> None:
    """Delete the document's metadata, chunks and all of its vectors."""
    await c.documents.delete(document_id)


@router.post("/{document_id}/reindex", response_model=DocumentOut)
async def reindex_document(document_id: str, c: Container = Depends(get_container)) -> DocumentOut:
    """Re-embed a document with the currently configured embedding model."""
    return await c.documents.reindex(document_id)
