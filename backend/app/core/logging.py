"""Logging setup.

Logs are structured as ``key=value`` pairs. Prompts, document text and answers are not
logged unless ``LOG_CONTENT=true``; use :func:`redact` when a log line might include them.
"""

from __future__ import annotations

import logging
import sys

_CONTENT_LOGGING = False


def configure_logging(level: str = "INFO", log_content: bool = False) -> None:
    global _CONTENT_LOGGING
    _CONTENT_LOGGING = log_content
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Third-party libraries are noisy at INFO.
    for name in ("httpx", "httpcore", "sentence_transformers", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)


def redact(text: str | None, keep: int = 0) -> str:
    """Return ``text`` only when content logging is enabled; otherwise a length marker."""
    if text is None:
        return "<none>"
    if _CONTENT_LOGGING:
        return text if keep <= 0 else text[:keep]
    return f"<redacted {len(text)} chars>"


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
