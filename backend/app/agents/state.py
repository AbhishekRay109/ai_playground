"""Typed state for the LangGraph agent. Scoped to a single request."""

from __future__ import annotations

from typing import Any, Literal, TypedDict


class ToolCall(TypedDict):
    tool: str
    arguments: dict[str, Any]
    purpose: str


class ToolResultRecord(TypedDict):
    tool: str
    arguments: dict[str, Any]
    status: str  # success | error | timeout | rejected
    summary: str
    observation: str


class AgentState(TypedDict, total=False):
    question: str
    history: list[dict[str, str]]  # prior conversation turns (role/content)
    available_tools: list[str]  # the user's allowlist for this request
    unavailable_tools: list[str]  # known tools the user disabled
    iterations: int
    tool_calls: int
    tool_results: list[ToolResultRecord]
    evidence_count: int  # number of citable evidence items gathered so far
    reasoning: list[str]  # concise, user-facing summaries (no hidden chain-of-thought)
    pending_call: ToolCall | None
    draft_answer: str | None  # answer proposed by the planner when no tools are needed
    next_step: Literal["call_tool", "final_answer", "validate_failed", "limit"]
    final_answer: str
    errors: list[dict[str, Any]]
