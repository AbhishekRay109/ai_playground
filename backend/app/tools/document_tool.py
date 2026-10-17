"""Document retrieval tool (Qdrant similarity search over uploaded documents)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.chat import Source, ToolName
from app.services.citations import excerpt
from app.tools.base import Evidence, Tool, ToolContext, ToolOutput, bound


class DocumentArgs(BaseModel):
    query: str = Field(min_length=1, max_length=500, description="What to look for in the uploaded documents")
    top_k: int | None = Field(default=None, ge=1, le=20, description="Number of chunks to retrieve")


class DocumentRetrievalTool(Tool):
    name = ToolName.DOCUMENT_RETRIEVAL
    description = "Search the user's uploaded documents (PDF, DOCX, TXT, Markdown) and return relevant passages."
    args_model = DocumentArgs

    async def run(self, args: DocumentArgs, ctx: ToolContext) -> ToolOutput:  # type: ignore[override]
        c = ctx.container
        n_docs = c.documents_repo.count()
        top_k = args.top_k or ctx.options.top_k
        result = await c.retrieval.retrieve(args.query, top_k, ctx.options.score_threshold, ctx.options.document_ids)
        chunks_detail = [
            {
                "chunk_id": ch.chunk_id,
                "document_id": ch.document_id,
                "filename": ch.filename,
                "page": ch.page,
                "chunk_index": ch.chunk_index,
                "score": round(ch.score, 4),
                "rerank_score": None if ch.rerank_score is None else round(ch.rerank_score, 4),
                "text": ch.text[:1200],
            }
            for ch in result.chunks
        ]
        details = {
            "query": args.query,
            "top_k": top_k,
            "score_threshold": result.score_threshold,
            "candidates": result.candidates,
            "reranked": result.reranked,
            "chunks": chunks_detail,
            "documents_indexed": n_docs,
            "notes": result.notes,
        }
        if not result.chunks:
            reason = (
                "No documents have been uploaded."
                if n_docs == 0
                else (result.notes[0] if result.notes else "No relevant chunks found.")
            )
            return ToolOutput(
                summary=f"Retrieved 0 chunks. {reason}",
                observation=f"No relevant document passages. {reason}",
                details=details,
                counts={"retrieved_chunks": 0},
                embedding_model=result.embedding_model,
            )
        evidence = [
            Evidence(
                source=Source(
                    id=0,
                    kind="document",
                    title=ch.filename + (f" (p. {ch.page})" if ch.page else ""),
                    excerpt=excerpt(ch.text, args.query),
                    document_id=ch.document_id,
                    filename=ch.filename,
                    page=ch.page,
                    chunk_id=ch.chunk_id,
                    chunk_index=ch.chunk_index,
                    score=round(ch.score, 4),
                ),
                text=ch.text,
            )
            for ch in result.chunks
        ]
        n_files = len({ch.document_id for ch in result.chunks})
        summary = f"Retrieved {len(result.chunks)} chunk(s) from {n_files} document(s)"
        observation = "\n".join(
            f"- {ch.filename}{f' p.{ch.page}' if ch.page else ''} (score {ch.score:.2f}): {ch.text[:300]}"
            for ch in result.chunks
        )
        return ToolOutput(
            summary=summary,
            observation=bound(observation, c.settings.tool_output_max_chars),
            evidence=evidence,
            details=details,
            counts={"retrieved_chunks": len(result.chunks)},
            embedding_model=result.embedding_model,
        )
