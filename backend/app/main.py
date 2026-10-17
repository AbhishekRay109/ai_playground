"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.routes import chat, documents, evaluation, sessions, system
from app.core.config import Settings, get_settings
from app.core.container import Container, build_container
from app.core.errors import AppError
from app.core.logging import configure_logging, get_logger
from app.core.middleware import BodySizeLimitMiddleware, RateLimitMiddleware, RequestIdMiddleware
from app.services.chat_service import ChatService

log = get_logger(__name__)
API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or (container.settings if container else get_settings())
    configure_logging(settings.log_level, settings.log_content)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN202
        if not hasattr(app.state, "container"):
            app.state.container = build_container(settings)
            app.state.chat_service = ChatService(app.state.container)
        log.info("startup env=%s vector_store=%s", settings.environment, app.state.container.vectors.description)
        yield
        if not container:  # injected containers are closed by their owner
            app.state.container.close()

    app = FastAPI(
        title="Open-Source AI Playground API",
        version=__version__,
        description="Local RAG, web search, SQL and agentic AI playground. Not a multi-tenant service.",
        lifespan=lifespan,
        docs_url=f"{API_PREFIX}/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    if container is not None:
        app.state.container = container
        app.state.chat_service = ChatService(container)

    # Middleware (last added runs first).
    app.add_middleware(
        RateLimitMiddleware,
        per_minute=settings.rate_limit_per_minute,
        paths=(f"{API_PREFIX}/chat", f"{API_PREFIX}/documents", f"{API_PREFIX}/evaluation"),
    )
    app.add_middleware(
        BodySizeLimitMiddleware,
        max_bytes=settings.max_request_bytes,
        upload_max_bytes=int(settings.max_upload_bytes * settings.max_files_per_upload + 1_000_000),
        upload_prefix=f"{API_PREFIX}/documents",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
        expose_headers=["X-Request-Id"],
    )
    app.add_middleware(RequestIdMiddleware)

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.to_dict()})

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]} for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "The request is invalid.",
                    "details": details,
                    "retryable": False,
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Stack traces are logged, never returned to the browser.
        log.exception("unhandled error path=%s", request.url.path)
        rid = request.scope.get("state", {}).get("request_id")
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "Internal server error.",
                    "request_id": rid,
                    "retryable": False,
                }
            },
        )

    for module in (chat, documents, sessions, system, evaluation):
        app.include_router(module.router, prefix=API_PREFIX)
    return app


app = create_app()
