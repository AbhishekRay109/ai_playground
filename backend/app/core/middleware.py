"""HTTP middleware: request ids, body size limits, simple per-IP rate limiting."""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import PayloadTooLarge, RateLimited


def _json_error(status: int, body: dict) -> tuple[list, bytes]:
    import json

    data = json.dumps({"error": body}).encode()
    return [(b"content-type", b"application/json"), (b"content-length", str(len(data)).encode())], data


class BodySizeLimitMiddleware:
    """Reject request bodies above a limit. Uploads use a separate, larger limit."""

    def __init__(self, app: ASGIApp, max_bytes: int, upload_max_bytes: int, upload_prefix: str) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.upload_max_bytes = upload_max_bytes
        self.upload_prefix = upload_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS", "DELETE"):
            await self.app(scope, receive, send)
            return
        limit = self.upload_max_bytes if scope["path"].startswith(self.upload_prefix) else self.max_bytes
        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await self._reject(send, limit)
            return
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise PayloadTooLarge(f"Request body exceeds {limit} bytes.")
            return message

        await self.app(scope, limited_receive, send)

    @staticmethod
    async def _reject(send: Send, limit: int) -> None:
        headers, body = _json_error(413, PayloadTooLarge(f"Request body exceeds {limit} bytes.").to_dict())
        await send({"type": "http.response.start", "status": 413, "headers": headers})
        await send({"type": "http.response.body", "body": body})


class RateLimitMiddleware:
    """Sliding-window limit per client IP for expensive POST endpoints (in-memory, single process)."""

    def __init__(self, app: ASGIApp, per_minute: int, paths: tuple[str, ...]) -> None:
        self.app = app
        self.per_minute = per_minute
        self.paths = paths
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or self.per_minute <= 0
            or scope["method"] != "POST"
            or not scope["path"].startswith(self.paths)
        ):
            await self.app(scope, receive, send)
            return
        client = (scope.get("client") or ("unknown", 0))[0]
        now = time.monotonic()
        hits = self._hits[client]
        while hits and now - hits[0] > 60:
            hits.popleft()
        if len(hits) >= self.per_minute:
            err = RateLimited("Too many requests. Please wait a moment and try again.")
            headers, body = _json_error(429, err.to_dict())
            await send({"type": "http.response.start", "status": 429, "headers": headers + [(b"retry-after", b"30")]})
            await send({"type": "http.response.body", "body": body})
            return
        hits.append(now)
        await self.app(scope, receive, send)


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid.uuid4().hex[:16]
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"] = [*message["headers"], (b"x-request-id", request_id.encode())]
            await send(message)

        await self.app(scope, receive, send_with_id)
