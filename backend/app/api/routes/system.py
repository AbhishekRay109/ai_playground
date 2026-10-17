"""Health, models and configuration endpoints."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends

from app import __version__
from app.api.deps import get_container
from app.core.container import Container
from app.core.errors import AppError, ValidationFailed
from app.schemas.common import (
    ConfigResponse,
    HealthResponse,
    ModelsResponse,
    RuntimeConfigUpdate,
    ServiceStatus,
)
from app.services.llm_service import SETUP_HINT

router = APIRouter(tags=["system"])


async def _timed(coro) -> tuple[object, int]:  # noqa: ANN001
    start = time.perf_counter()
    result = await coro
    return result, int((time.perf_counter() - start) * 1000)


@router.get("/health", response_model=HealthResponse)
async def health(c: Container = Depends(get_container)) -> HealthResponse:
    """Check the status of every local dependency. Never raises; reports problems with hints."""
    services: dict[str, ServiceStatus] = {}

    async def check_llm() -> ServiceStatus:
        try:
            models, ms = await _timed(c.llm.list_models())
        except AppError as exc:
            return ServiceStatus(ok=False, detail=exc.message, hint=exc.hint)
        names = [m.name for m in models]  # type: ignore[attr-defined]
        model = c.runtime.current.chat_model
        if model not in names:
            return ServiceStatus(
                ok=False,
                detail=f"Ollama is running but model '{model}' is not installed.",
                hint=f"Run `ollama pull {model}` or pick an installed model in Settings.",
                latency_ms=ms,
            )
        return ServiceStatus(ok=True, detail=f"{len(names)} model(s) installed; using {model}", latency_ms=ms)

    async def check_search() -> ServiceStatus:
        ok, detail = await c.search.searxng.health()
        return ServiceStatus(
            ok=ok,
            detail=f"SearXNG at {c.settings.searxng_url}: {detail}",
            hint=None if ok else "Start SearXNG (docker compose up searxng) or set SEARXNG_URL.",
        )

    async def check_embeddings() -> ServiceStatus:
        try:
            embedder = c.embeddings.get()
            dim = await asyncio.wait_for(asyncio.to_thread(lambda: embedder.dimension), timeout=60)
            return ServiceStatus(ok=True, detail=f"{embedder.model_name} ({c.embeddings.provider}, dim {dim})")
        except AppError as exc:
            return ServiceStatus(ok=False, detail=exc.message, hint=exc.hint)
        except TimeoutError:
            return ServiceStatus(ok=False, detail="Embedding model is still loading.")

    llm_s, search_s, emb_s = await asyncio.gather(check_llm(), check_search(), check_embeddings())
    services["llm"], services["web_search"], services["embeddings"] = llm_s, search_s, emb_s
    ok, detail = await asyncio.to_thread(c.vectors.health)
    services["vector_store"] = ServiceStatus(ok=ok, detail=detail)
    services["sql_demo_db"] = ServiceStatus(
        ok=c.settings.resolved_demo_db_path.exists(), detail="read-only sample database"
    )
    status = "ok" if all(s.ok for s in services.values()) else "degraded"
    return HealthResponse(status=status, version=__version__, services=services)


@router.get("/models", response_model=ModelsResponse)
async def models(c: Container = Depends(get_container)) -> ModelsResponse:
    """List models installed in the local Ollama instance (nothing is downloaded)."""
    current = c.runtime.current.chat_model
    try:
        installed = await c.llm.list_models()
    except AppError as exc:
        return ModelsResponse(available=False, current_model=current, error=exc.message, hint=exc.hint or SETUP_HINT)
    return ModelsResponse(available=True, models=installed, current_model=current)


def _config_response(c: Container, warnings: list[str] | None = None) -> ConfigResponse:
    s = c.settings
    return ConfigResponse(
        runtime=c.runtime.current,
        embedding_provider=s.embedding_provider,
        ollama_base_url=s.ollama_base_url,
        searxng_url=s.searxng_url,
        vector_store=c.vectors.description,
        limits={
            "max_upload_mb": s.max_upload_mb,
            "max_files_per_upload": s.max_files_per_upload,
            "max_documents": s.max_documents,
            "chunk_size": s.chunk_size,
            "chunk_overlap": s.chunk_overlap,
            "sql_row_limit": s.sql_row_limit,
            "sql_timeout_s": s.sql_timeout_s,
            "agent_max_iterations": s.agent_max_iterations,
            "agent_max_tool_calls": s.agent_max_tool_calls,
            "agent_tool_timeout_s": s.agent_tool_timeout_s,
            "agent_request_timeout_s": s.agent_request_timeout_s,
            "max_question_chars": s.max_question_chars,
            "search_results": s.search_results,
            "web_fetch_pages": s.web_fetch_pages,
        },
        warnings=warnings or [],
    )


@router.get("/config", response_model=ConfigResponse)
async def get_config(c: Container = Depends(get_container)) -> ConfigResponse:
    """Public, non-secret configuration."""
    return _config_response(c)


@router.put("/config", response_model=ConfigResponse)
async def update_config(update: RuntimeConfigUpdate, c: Container = Depends(get_container)) -> ConfigResponse:
    """Update user-adjustable settings. Models are validated but never downloaded."""
    warnings: list[str] = []
    if update.chat_model:
        try:
            names = [m.name for m in await c.llm.list_models()]
        except AppError:
            warnings.append("Ollama is not reachable, so the model name could not be verified.")
        else:
            if update.chat_model not in names:
                raise ValidationFailed(
                    f"Model '{update.chat_model}' is not installed in Ollama.",
                    hint=f"Run `ollama pull {update.chat_model}` first.",
                    code="model_not_installed",
                )
    if update.embedding_model and update.embedding_model != c.runtime.current.embedding_model:
        previous = c.embeddings.model_name
        c.embeddings.set_model(update.embedding_model)
        try:
            await asyncio.to_thread(lambda: c.embeddings.get().dimension)
        except AppError as exc:
            c.embeddings.set_model(previous)
            raise ValidationFailed(exc.message, hint=exc.hint, code="embedding_model_unavailable") from exc
        warnings.append("Embedding model changed: existing documents are marked stale until re-indexed.")
    c.runtime.update(update)
    return _config_response(c, warnings)


@router.post("/config/reset", response_model=ConfigResponse)
async def reset_config(c: Container = Depends(get_container)) -> ConfigResponse:
    rt = c.runtime.reset()
    c.embeddings.set_model(rt.embedding_model)
    return _config_response(c)
