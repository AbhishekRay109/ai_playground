"""SQL tool: natural-language question → validated read-only query over the demo database.

The agent passes a *question*, not raw SQL. The SQL is generated and then independently
validated and executed under read-only enforcement by :mod:`app.services.sql_safety`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.chat import Source, ToolName
from app.services.llm_service import LLMOptions
from app.services.sql_service import rows_as_markdown
from app.tools.base import Evidence, Tool, ToolContext, ToolOutput, bound


class SqlArgs(BaseModel):
    question: str = Field(
        min_length=1,
        max_length=500,
        description="Question about the sample sales database (products, orders, customers)",
    )


class SqlTool(Tool):
    name = ToolName.SQL_QUERY
    description = (
        "Answer questions about the sample business database (customers, products, orders, "
        "order_items, monthly_sales) with a validated read-only SQL query."
    )
    args_model = SqlArgs

    async def run(self, args: SqlArgs, ctx: ToolContext) -> ToolOutput:  # type: ignore[override]
        c = ctx.container
        o = ctx.options
        outcome = await c.sql.answer_question(
            args.question, LLMOptions(model=o.model, temperature=0.0, max_tokens=512, timeout_s=o.timeout_s)
        )
        details = {
            "question": args.question,
            "sql": outcome.sql,
            "explanation": outcome.explanation,
            "attempts": [a.__dict__ for a in outcome.attempts],
        }
        if outcome.result is None:
            msg = outcome.error.message if outcome.error else "The query could not be produced."
            details["error"] = msg
            return ToolOutput(
                summary=f"No query executed: {msg}",
                observation=f"SQL tool error: {msg}",
                details=details,
                status="error",
                error=msg,
                llm_results=outcome.llm_results,
            )
        r = outcome.result
        details.update(
            {
                "columns": r.columns,
                "rows": r.rows[:100],
                "row_count": r.row_count,
                "truncated": r.truncated,
                "execution_ms": r.latency_ms,
            }
        )
        table = rows_as_markdown(r.columns, r.rows, limit=50)
        evidence_text = (
            f"SQL: {outcome.sql}\nRows returned: {r.row_count}{' (truncated)' if r.truncated else ''}\n{table}"
        )
        source = Source(
            id=0,
            kind="sql",
            title="Sample database query result",
            excerpt=table[:400],
            sql=outcome.sql,
            row_count=r.row_count,
        )
        summary = f"Executed validated SELECT; {r.row_count} row(s){' (truncated)' if r.truncated else ''}"
        return ToolOutput(
            summary=summary,
            observation=bound(evidence_text, c.settings.tool_output_max_chars),
            evidence=[Evidence(source=source, text=evidence_text)],
            details=details,
            counts={"sql_rows": r.row_count},
            llm_results=outcome.llm_results,
        )
