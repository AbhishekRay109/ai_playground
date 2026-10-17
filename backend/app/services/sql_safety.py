"""Independent SQL safety layer for the SQL Assistant.

The LLM is never trusted to enforce safety. A query must pass *both*:

1. **Static validation** (:func:`validate_sql`, using ``sqlglot``): exactly one statement,
   a read-only ``SELECT``/``WITH``/set operation, only allowlisted tables (or CTEs defined
   in the query), no schema-qualified names, and only allowlisted functions.
2. **Runtime enforcement** (:class:`ReadOnlyExecutor`): a separate ``mode=ro`` SQLite
   connection with ``PRAGMA query_only``, an SQLite authorizer that only allows reads of
   allowlisted tables and allowlisted functions, a progress-handler timeout and a row cap.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sqlglot
from sqlglot import exp

from app.core.errors import SQLExecutionError, SQLValidationError

MAX_SQL_CHARS = 4000

# Functions a read-only analytics query may call. Anything else (load_extension, readfile,
# randomblob, ...) is rejected statically and by the authorizer at run time.
ALLOWED_FUNCTIONS = frozenset(
    {
        "abs",
        "avg",
        "count",
        "max",
        "min",
        "sum",
        "total",
        "group_concat",
        "round",
        "coalesce",
        "ifnull",
        "nullif",
        "lower",
        "upper",
        "length",
        "substr",
        "substring",
        "trim",
        "ltrim",
        "rtrim",
        "replace",
        "instr",
        "date",
        "time",
        "datetime",
        "julianday",
        "strftime",
        "cast",
        "iif",
        "printf",
        "format",
        "like",
        "glob",
        "typeof",
        "unixepoch",
        "row_number",
        "rank",
        "dense_rank",
        "lag",
        "lead",
        "first_value",
        "last_value",
        "ntile",
        "percent_rank",
        "cume_dist",
    }
)

_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = tuple(
    t
    for t in (
        getattr(exp, name, None)
        for name in (
            "Insert",
            "Update",
            "Delete",
            "Create",
            "Drop",
            "Alter",
            "Command",
            "Pragma",
            "Attach",
            "Detach",
            "Merge",
            "TruncateTable",
            "Into",
            "Transaction",
            "Commit",
            "Rollback",
            "Set",
            "Use",
            "Copy",
            "LoadData",
            "Analyze",
        )
    )
    if t is not None
)


@dataclass
class ValidatedQuery:
    sql: str
    tables: list[str]


def _function_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    return node.sql_name().lower()


def validate_sql(sql: str, allowed_tables: list[str]) -> ValidatedQuery:
    """Validate ``sql`` or raise :class:`SQLValidationError` with a user-facing reason."""
    if not sql or not sql.strip():
        raise SQLValidationError("The generated SQL is empty.")
    if len(sql) > MAX_SQL_CHARS:
        raise SQLValidationError(f"The SQL is too long ({len(sql)} characters).")
    allowed = {t.lower() for t in allowed_tables}
    try:
        statements = [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
    except sqlglot.errors.SqlglotError as exc:
        raise SQLValidationError(f"The SQL could not be parsed: {str(exc).splitlines()[0][:200]}") from exc
    if len(statements) != 1:
        raise SQLValidationError("Exactly one SQL statement is allowed.")
    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise SQLValidationError(f"Only read-only SELECT queries are allowed (got {tree.key.upper()}).")

    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise SQLValidationError(f"{node.key.upper()} is not allowed in read-only queries.")

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    tables: list[str] = []
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        if table.args.get("db") or table.args.get("catalog"):
            raise SQLValidationError(f"Schema-qualified table '{table.sql()}' is not allowed.")
        if not name:
            raise SQLValidationError("Table-valued functions are not allowed.")
        if name in cte_names:
            continue
        if name not in allowed:
            raise SQLValidationError(
                f"Table '{table.name}' is not an approved table. Allowed: {', '.join(sorted(allowed))}."
            )
        tables.append(name)

    for func in tree.find_all(exp.Func):
        fname = _function_name(func)
        if isinstance(func, exp.Anonymous) and fname not in ALLOWED_FUNCTIONS:
            raise SQLValidationError(f"Function '{fname}' is not allowed.")
        if fname.startswith(("load_extension", "readfile", "writefile", "fts3", "sqlite_")):
            raise SQLValidationError(f"Function '{fname}' is not allowed.")

    return ValidatedQuery(sql=sql.strip().rstrip(";").strip(), tables=sorted(set(tables)))


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    latency_ms: int


def _json_safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    return value


def readonly_uri(db_path: Path) -> str:
    """SQLite URI that opens ``db_path`` read-only.

    ``Path.as_uri`` percent-encodes the path and adds the leading slash Windows
    drive letters need (``file:///C:/...``), so this works on every platform.
    """
    return f"{db_path.resolve().as_uri()}?mode=ro"


class ReadOnlyExecutor:
    def __init__(self, db_path: Path, allowed_tables: list[str], row_limit: int, timeout_s: float) -> None:
        self.db_path = db_path
        self.allowed_tables = {t.lower() for t in allowed_tables}
        self.row_limit = row_limit
        self.timeout_s = timeout_s

    def _authorizer(self, action: int, arg1: str | None, arg2: str | None, db: str | None, _trigger: str | None) -> int:
        if action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            table = (arg1 or "").lower()
            # Real tables are reported with db="main"; CTEs and subqueries have no database.
            if (db == "main" and table in self.allowed_tables) or db is None:
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION:
            return sqlite3.SQLITE_OK if (arg2 or "").lower() in ALLOWED_FUNCTIONS else sqlite3.SQLITE_DENY
        if action == getattr(sqlite3, "SQLITE_RECURSIVE", 33):
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    def execute(self, query: ValidatedQuery) -> QueryResult:
        if not self.db_path.exists():
            raise SQLExecutionError("The demo database does not exist yet.")
        start = time.perf_counter()
        deadline = start + self.timeout_s
        conn = sqlite3.connect(readonly_uri(self.db_path), uri=True, timeout=self.timeout_s, check_same_thread=False)
        try:
            conn.execute("PRAGMA query_only = ON")
            conn.set_authorizer(self._authorizer)
            conn.set_progress_handler(lambda: 1 if time.perf_counter() > deadline else 0, 2000)
            try:
                cur = conn.execute(query.sql)
                rows = cur.fetchmany(self.row_limit + 1)
            except sqlite3.DatabaseError as exc:
                msg = str(exc)
                if "interrupted" in msg:
                    raise SQLExecutionError(f"The query exceeded the {self.timeout_s:g}s time limit.") from exc
                if "not authorized" in msg or "prohibited" in msg:
                    raise SQLExecutionError("The query was blocked by the read-only policy.") from exc
                raise SQLExecutionError(f"The database rejected the query: {msg[:200]}") from exc
            columns = [d[0] for d in (cur.description or [])]
        finally:
            conn.close()
        truncated = len(rows) > self.row_limit
        rows = rows[: self.row_limit]
        return QueryResult(
            columns=columns,
            rows=[[_json_safe(v) for v in r] for r in rows],
            row_count=len(rows),
            truncated=truncated,
            latency_ms=int((time.perf_counter() - start) * 1000),
        )
