"""Tool registry and allowlisting."""

from __future__ import annotations

from app.schemas.chat import ToolName
from app.tools.base import Tool
from app.tools.calculator_tool import CalculatorTool
from app.tools.document_tool import DocumentRetrievalTool
from app.tools.sql_tool import SqlTool
from app.tools.web_search_tool import WebSearchTool

ALL_TOOLS: dict[ToolName, Tool] = {
    ToolName.DOCUMENT_RETRIEVAL: DocumentRetrievalTool(),
    ToolName.WEB_SEARCH: WebSearchTool(),
    ToolName.SQL_QUERY: SqlTool(),
    ToolName.CALCULATOR: CalculatorTool(),
}


def enabled_tools(names: list[ToolName]) -> dict[str, Tool]:
    """Return only the tools the user enabled (the agent's allowlist for this request)."""
    return {n.value: ALL_TOOLS[n] for n in names if n in ALL_TOOLS}
