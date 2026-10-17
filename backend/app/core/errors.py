"""Application errors.

Every error that may reach the browser is an :class:`AppError` with a stable ``code``, a
user-safe ``message`` and an optional ``hint`` describing how to fix the setup. Stack traces
and internal details are only logged server-side.
"""

from __future__ import annotations


class AppError(Exception):
    code = "app_error"
    status_code = 500
    retryable = False

    def __init__(
        self, message: str, *, hint: str | None = None, code: str | None = None, status_code: int | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code

    def to_dict(self) -> dict:
        data = {"code": self.code, "message": self.message, "retryable": self.retryable}
        if self.hint:
            data["hint"] = self.hint
        return data


class ValidationFailed(AppError):
    code = "validation_error"
    status_code = 422


class NotFound(AppError):
    code = "not_found"
    status_code = 404


class Conflict(AppError):
    code = "conflict"
    status_code = 409


class PayloadTooLarge(AppError):
    code = "payload_too_large"
    status_code = 413


class RateLimited(AppError):
    code = "rate_limited"
    status_code = 429
    retryable = True


class ServiceUnavailable(AppError):
    """A local dependency (Ollama, SearXNG, embedding model, ...) is not reachable."""

    code = "service_unavailable"
    status_code = 503
    retryable = True


class LLMUnavailable(ServiceUnavailable):
    code = "llm_unavailable"


class LLMModelNotFound(AppError):
    code = "llm_model_not_found"
    status_code = 400


class LLMTimeout(ServiceUnavailable):
    code = "llm_timeout"


class LLMError(AppError):
    code = "llm_error"
    status_code = 502
    retryable = True


class EmbeddingUnavailable(ServiceUnavailable):
    code = "embedding_unavailable"


class SearchUnavailable(ServiceUnavailable):
    code = "search_unavailable"


class SearchRateLimited(ServiceUnavailable):
    code = "search_rate_limited"
    status_code = 429


class SQLValidationError(AppError):
    code = "sql_rejected"
    status_code = 400


class SQLExecutionError(AppError):
    code = "sql_execution_error"
    status_code = 400


class ToolError(AppError):
    code = "tool_error"
    status_code = 500


class ToolTimeout(ToolError):
    code = "tool_timeout"
    retryable = True
