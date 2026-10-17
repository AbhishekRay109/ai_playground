"""SQL Assistant: natural language → validated read-only SQL → results → explanation."""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.core.errors import AppError, SQLExecutionError, SQLValidationError
from app.services.demo_db import TABLE_DESCRIPTIONS
from app.services.llm_service import ChatMessage, LLMClient, LLMOptions, LLMResult
from app.services.prompts import SQL_GENERATION_SYSTEM
from app.services.sql_safety import QueryResult, ReadOnlyExecutor, ValidatedQuery, readonly_uri, validate_sql

SQL_SCHEMA_FORMAT = {
    "type": "object",
    "properties": {"sql": {"type": "string"}, "explanation": {"type": "string"}},
    "required": ["sql", "explanation"],
}


@dataclass
class SqlAttempt:
    sql: str
    status: str  # valid | rejected | execution_error | success
    error: str | None = None


@dataclass
class SqlOutcome:
    question: str
    sql: str | None
    explanation: str
    result: QueryResult | None
    attempts: list[SqlAttempt] = field(default_factory=list)
    llm_results: list[LLMResult] = field(default_factory=list)
    error: AppError | None = None
    latency_ms: int = 0


def parse_sql_response(text: str) -> tuple[str, str]:
    """Extract ``(sql, explanation)`` from the model output (JSON, or a fenced SQL block)."""
    text = text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return str(data.get("sql") or "").strip(), str(data.get("explanation") or "").strip()
    except ValueError:
        pass
    match = re.search(r"```(?:sql)?\s*(.+?)```", text, re.S | re.I)
    if match:
        return match.group(1).strip(), ""
    match = re.search(r"((?:WITH|SELECT)\b.+)", text, re.S | re.I)
    return (match.group(1).strip() if match else ""), ""


class SqlService:
    def __init__(self, settings: Settings, llm: LLMClient, db_path: Path) -> None:
        self.settings = settings
        self.llm = llm
        self.db_path = db_path
        self.executor = ReadOnlyExecutor(
            db_path, settings.sql_allowed_tables, settings.sql_row_limit, settings.sql_timeout_s
        )
        self._schema_cache: str | None = None

    def schema_description(self) -> str:
        """Describe only the allowlisted tables (columns, types, keys, two sample rows)."""
        if self._schema_cache:
            return self._schema_cache
        conn = sqlite3.connect(readonly_uri(self.db_path), uri=True)
        try:
            parts = []
            for table in self.settings.sql_allowed_tables:
                cols = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
                if not cols:
                    continue
                fks = conn.execute(f'PRAGMA foreign_key_list("{table}")').fetchall()
                col_desc = ", ".join(f"{c[1]} {c[2]}{' PK' if c[5] else ''}" for c in cols)
                fk_desc = "; ".join(f"{f[3]} -> {f[2]}.{f[4]}" for f in fks)
                sample = conn.execute(f'SELECT * FROM "{table}" LIMIT 2').fetchall()
                parts.append(
                    f"TABLE {table} ({col_desc})"
                    + (f"\n  foreign keys: {fk_desc}" if fk_desc else "")
                    + (f"\n  note: {TABLE_DESCRIPTIONS[table]}" if table in TABLE_DESCRIPTIONS else "")
                    + f"\n  sample rows: {sample}"
                )
        finally:
            conn.close()
        self._schema_cache = "\n".join(parts)
        return self._schema_cache

    async def answer_question(self, question: str, options: LLMOptions, max_attempts: int = 2) -> SqlOutcome:
        """Generate, validate and execute SQL. One repair attempt is made after a rejection."""
        start = time.perf_counter()
        schema = await asyncio.to_thread(self.schema_description)
        messages = [
            ChatMessage("system", SQL_GENERATION_SYSTEM + "\n\nSchema:\n" + schema),
            ChatMessage("user", f"Question: {question}"),
        ]
        outcome = SqlOutcome(question=question, sql=None, explanation="", result=None)
        gen_options = LLMOptions(
            model=options.model, temperature=0.0, max_tokens=512, timeout_s=options.timeout_s, format=SQL_SCHEMA_FORMAT
        )
        for _attempt in range(max_attempts):
            llm_result = await self.llm.chat(messages, gen_options)
            outcome.llm_results.append(llm_result)
            sql, explanation = parse_sql_response(llm_result.text)
            if not sql:
                outcome.explanation = explanation or "The model could not express this question as a query."
                outcome.error = SQLValidationError(
                    "The question could not be answered from the sample database schema."
                    + (f" {explanation}" if explanation else "")
                )
                break
            try:
                validated: ValidatedQuery = validate_sql(sql, self.settings.sql_allowed_tables)
            except SQLValidationError as exc:
                outcome.attempts.append(SqlAttempt(sql=sql, status="rejected", error=exc.message))
                outcome.sql, outcome.error = sql, exc
                messages += [
                    ChatMessage("assistant", llm_result.text),
                    ChatMessage(
                        "user",
                        f"That query was rejected by the validator: {exc.message} "
                        "Return a corrected read-only SELECT query as JSON.",
                    ),
                ]
                continue
            outcome.sql, outcome.explanation = validated.sql, explanation
            try:
                outcome.result = await asyncio.to_thread(self.executor.execute, validated)
            except SQLExecutionError as exc:
                outcome.attempts.append(SqlAttempt(sql=validated.sql, status="execution_error", error=exc.message))
                outcome.error = exc
                messages += [
                    ChatMessage("assistant", llm_result.text),
                    ChatMessage("user", f"The query failed: {exc.message} Return a corrected query as JSON."),
                ]
                continue
            outcome.attempts.append(SqlAttempt(sql=validated.sql, status="success"))
            outcome.error = None
            break
        outcome.latency_ms = int((time.perf_counter() - start) * 1000)
        return outcome


def rows_as_markdown(columns: list[str], rows: list[list[Any]], limit: int = 50) -> str:
    if not columns:
        return "(no columns)"
    head = "| " + " | ".join(columns) + " |\n| " + " | ".join("---" for _ in columns) + " |"
    body = "\n".join("| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in rows[:limit])
    more = f"\n… {len(rows) - limit} more rows not shown" if len(rows) > limit else ""
    return head + ("\n" + body if body else "\n(no rows)") + more
