import json

import pytest

from app.core.errors import SQLExecutionError, SQLValidationError
from app.services.sql_safety import ReadOnlyExecutor, ValidatedQuery, validate_sql
from app.services.sql_service import parse_sql_response

TABLES = ["customers", "products", "orders", "order_items", "monthly_sales"]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT name FROM products",
        "select p.name, sum(oi.quantity) q from order_items oi join products p on p.id = oi.product_id group by 1 order by q desc limit 5",  # noqa: E501
        "WITH t AS (SELECT product_id, SUM(revenue) r FROM monthly_sales GROUP BY 1) SELECT * FROM t",
        "SELECT strftime('%Y', order_date), COUNT(*) FROM orders GROUP BY 1",
        "SELECT name FROM products UNION SELECT name FROM customers",
        "SELECT category, AVG(unit_price) FROM products GROUP BY category;",
    ],
)
def test_valid_read_only_queries(sql):
    assert validate_sql(sql, TABLES).sql


@pytest.mark.parametrize(
    "sql,reason",
    [
        ("DELETE FROM orders", "read-only"),
        ("UPDATE products SET unit_price = 0", "read-only"),
        ("INSERT INTO orders (id) VALUES (1)", "read-only"),
        ("DROP TABLE orders", "read-only"),
        ("CREATE TABLE x (a int)", "read-only"),
        ("ALTER TABLE orders ADD COLUMN x int", "read-only"),
        ("SELECT 1; DROP TABLE orders", "one SQL statement"),
        ("SELECT * FROM orders; SELECT * FROM products", "one SQL statement"),
        ("PRAGMA table_info(orders)", "read-only"),
        ("ATTACH DATABASE '/tmp/x.db' AS x", "read-only|parsed"),  # older sqlglot cannot parse ATTACH
        ("SELECT * FROM sqlite_master", "not an approved table"),
        ("SELECT * FROM users", "not an approved table"),
        ("SELECT * FROM main.orders", "Schema-qualified"),
        ("SELECT load_extension('evil')", "not allowed"),
        ("SELECT readfile('/etc/passwd')", "not allowed"),
        ("SELECT randomblob(1000000000)", "not allowed"),
        ("", "empty"),
        ("SELEC broken", "parsed|read-only"),
        ("SELECT * FROM (", "parsed"),
    ],
)
def test_rejected_queries(sql, reason):
    with pytest.raises(SQLValidationError, match=reason):
        validate_sql(sql, TABLES)


def test_executor_enforces_read_only_even_without_validator(container):
    ex = container.sql.executor
    for sql in ("DELETE FROM orders", "SELECT * FROM sqlite_master", "UPDATE products SET unit_price = 1"):
        with pytest.raises(SQLExecutionError):
            ex.execute(ValidatedQuery(sql=sql, tables=[]))
    # data unchanged
    result = ex.execute(validate_sql("SELECT COUNT(*) FROM orders", TABLES))
    assert result.rows[0][0] == 900


def test_executor_row_limit_and_timeout(container):
    ex = ReadOnlyExecutor(container.settings.resolved_demo_db_path, TABLES, row_limit=10, timeout_s=0.05)
    result = ex.execute(validate_sql("SELECT * FROM orders", TABLES))
    assert result.row_count == 10 and result.truncated
    with pytest.raises(SQLExecutionError, match="time limit"):
        ex.execute(
            validate_sql(
                "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT COUNT(*) FROM c", TABLES
            )
        )


def test_parse_sql_response_formats():
    assert parse_sql_response(json.dumps({"sql": "SELECT 1", "explanation": "x"})) == ("SELECT 1", "x")
    assert parse_sql_response("```sql\nSELECT 2\n```")[0] == "SELECT 2"
    assert parse_sql_response("Here: SELECT 3 FROM products")[0] == "SELECT 3 FROM products"


def test_schema_description_lists_only_allowed_tables(container):
    container.settings.sql_allowed_tables = ["products"]
    container.sql._schema_cache = None
    desc = container.sql.schema_description()
    assert "TABLE products" in desc and "customers" not in desc


def _sql_llm(sql_first: str, sql_second: str | None = None, answer: str = "Echo Wireless Earbuds sold most [1]."):
    calls = {"n": 0}

    def respond(messages):
        if "translate questions" in messages[0].content:
            calls["n"] += 1
            sql = sql_first if calls["n"] == 1 or sql_second is None else sql_second
            return json.dumps({"sql": sql, "explanation": "top product by units"})
        return answer

    return respond


def test_sql_mode_success(client, llm):
    llm.responder = _sql_llm(
        "SELECT p.name, SUM(m.units_sold) AS units FROM monthly_sales m JOIN products p ON p.id = m.product_id "
        "GROUP BY p.name ORDER BY units DESC LIMIT 1"
    )
    data = client.post("/api/v1/chat", json={"question": "Highest-selling product?", "mode": "sql"}).json()
    assert data["status"] == "success"
    step = next(s for s in data["steps"] if s["name"] == "sql_query")
    assert step["details"]["rows"][0][0] == "Echo Wireless Earbuds"
    assert data["counts"]["sql_rows"] == 1
    assert data["sources"][0]["kind"] == "sql" and data["sources"][0]["cited"]
    assert data["executed_tools"] == ["sql_query"]


def test_sql_mode_rejects_write_query_and_does_not_execute(client, llm):
    llm.responder = _sql_llm("DELETE FROM orders", "DROP TABLE orders")
    data = client.post("/api/v1/chat", json={"question": "Delete all orders", "mode": "sql"}).json()
    assert data["status"] == "error"
    step = next(s for s in data["steps"] if s["name"] == "sql_query")
    assert [a["status"] for a in step["details"]["attempts"]] == ["rejected", "rejected"]
    assert "rows" not in step["details"]
    assert "could not answer" in data["answer"]
    # The database is untouched.
    assert (
        client.app.state.container.sql.executor.execute(validate_sql("SELECT COUNT(*) FROM orders", TABLES)).rows[0][0]
        == 900
    )


def test_sql_mode_repairs_after_rejection(client, llm):
    llm.responder = _sql_llm("SELECT * FROM secret_table", "SELECT COUNT(*) AS n FROM customers")
    data = client.post("/api/v1/chat", json={"question": "How many customers?", "mode": "sql"}).json()
    step = next(s for s in data["steps"] if s["name"] == "sql_query")
    assert [a["status"] for a in step["details"]["attempts"]] == ["rejected", "success"]
    assert step["details"]["rows"] == [[120]]


def test_readonly_uri_handles_spaces_and_special_characters(tmp_path):
    # Windows user folders often contain spaces; '#' and '%' would break a hand-built URI.
    import sqlite3

    from app.services.demo_db import create_demo_db
    from app.services.sql_safety import readonly_uri

    db_path = tmp_path / "My Projects #1 100%" / "demo.db"
    db_path.parent.mkdir()
    create_demo_db(db_path, n_customers=5, n_orders=10)

    uri = readonly_uri(db_path)
    assert uri.startswith("file:///") and uri.endswith("?mode=ro")
    conn = sqlite3.connect(uri, uri=True)
    try:
        assert conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 5
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM customers")
    finally:
        conn.close()
