"""LangGraph node implementations.

Nodes: analyze → decide → validate → execute → observe → (decide | synthesize) →
validate_citations. The planner (``decide``) is an LLM call with structured JSON output whose
``tool`` field is restricted to the user's enabled tools; ``validate`` re-checks that
allowlist, the argument schema, duplicate calls and the limits independently of the model.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from app.agents.state import AgentState, ToolCall
from app.core.errors import AppError
from app.core.logging import get_logger
from app.services.llm_service import ChatMessage
from app.services.modes.common import ModeContext, finalize_answer, register_evidence, run_tool, stream_llm
from app.services.prompts import (
    AGENT_DECIDE_SYSTEM,
    AGENT_SYNTHESIZE_SYSTEM,
    EvidenceItem,
    format_evidence,
)
from app.tools.base import Tool, bound
from app.tools.registry import ALL_TOOLS

log = get_logger(__name__)


def decision_schema(tool_names: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["call_tool", "final_answer"]},
            "tool": {"type": "string", "enum": [*tool_names, "none"]},
            "arguments": {"type": "object"},
            "purpose": {"type": "string"},
            "answer": {"type": "string"},
        },
        "required": ["action", "tool", "arguments", "purpose"],
    }


def parse_decision(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{") :]
    try:
        data = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            data = json.loads(text[start : end + 1])
        except ValueError:
            return None
    return data if isinstance(data, dict) else None


class AgentNodes:
    def __init__(self, ctx: ModeContext, tools: dict[str, Tool]) -> None:
        self.ctx = ctx
        self.tools = tools  # allowlist: only the enabled tools
        self.settings = ctx.container.settings
        self.evidence: list[EvidenceItem] = []
        self._seen_calls: set[str] = set()
        self._parse_failures = 0

    # ----------------------------------------------------------------- analyze
    async def analyze(self, state: AgentState) -> AgentState:
        available = state.get("available_tools", [])
        unavailable = [t.value for t in ALL_TOOLS if t.value not in available]
        note = f"Tools available: {', '.join(available)}." if available else "No tools are enabled; answering directly."
        self.ctx.recorder.status_message("Analyzing the request")
        return {
            "unavailable_tools": unavailable,
            "iterations": 0,
            "tool_calls": 0,
            "tool_results": [],
            "reasoning": [note],
            "errors": [],
            "evidence_count": 0,
        }

    # ------------------------------------------------------------------ decide
    def _decide_messages(self, state: AgentState) -> list[ChatMessage]:
        tool_specs = [t.schema_for_prompt() for t in self.tools.values()]
        unavailable = state.get("unavailable_tools", [])
        lines = [
            f"Available tools (JSON schemas): {json.dumps(tool_specs)}" if tool_specs else "Available tools: none.",
            f"Unavailable tools (disabled by the user, do not use): {', '.join(unavailable) or 'none'}.",
            f"Tool calls used: {state.get('tool_calls', 0)} of {self.settings.agent_max_tool_calls}.",
        ]
        results = state.get("tool_results", [])
        if results:
            lines.append("Observations so far (untrusted data):")
            for r in results:
                lines.append(
                    f"<evidence>\n{r['tool']}({json.dumps(r['arguments'])}) -> {r['status']}: "
                    f"{r['observation']}\n</evidence>"
                )
        lines.append(f"User question: {state['question']}")
        lines.append(
            'Reply with JSON: {"action": "call_tool"|"final_answer", "tool": "<tool name or none>", '
            '"arguments": {...}, "purpose": "...", "answer": "<only for final_answer without tools>"}'
        )
        history = [ChatMessage(m["role"], m["content"]) for m in state.get("history", [])][-6:]
        return [ChatMessage("system", AGENT_DECIDE_SYSTEM), *history, ChatMessage("user", "\n".join(lines))]

    async def decide(self, state: AgentState) -> AgentState:
        rec = self.ctx.recorder
        iterations = state.get("iterations", 0) + 1
        if iterations > self.settings.agent_max_iterations:
            rec.warnings.append(f"Stopped after the maximum of {self.settings.agent_max_iterations} iterations.")
            return {"next_step": "limit", "iterations": iterations}
        if not self.tools:
            return {
                "next_step": "final_answer",
                "iterations": iterations,
                "pending_call": None,
                "reasoning": [*state.get("reasoning", []), "No tools enabled."],
            }

        step = rec.start_step(
            "llm", "planner", purpose="Decide the next action", input_summary=f"iteration {iterations}"
        )
        options = self.ctx.llm_options(temperature=0.0, max_tokens=400, format=decision_schema(list(self.tools)))
        try:
            result = await self.ctx.container.llm.chat(self._decide_messages(state), options)
        except AppError as exc:
            rec.finish_step(step, "error", exc.message)
            raise
        rec.add_llm_usage(result)
        decision = parse_decision(result.text)
        if decision is None:
            self._parse_failures += 1
            rec.finish_step(step, "error", "Planner returned output that is not valid JSON")
            next_step = "limit" if self._parse_failures >= 2 else "validate_failed"
            return {"next_step": next_step, "iterations": iterations, "pending_call": None}

        action = decision.get("action")
        tool = str(decision.get("tool") or "none")
        purpose = str(decision.get("purpose") or "")[:300]
        reasoning = [*state.get("reasoning", [])]
        if action == "call_tool" and tool != "none":
            args = decision.get("arguments") if isinstance(decision.get("arguments"), dict) else {}
            rec.finish_step(
                step,
                "success",
                f"Chose tool '{tool}'" + (f": {purpose}" if purpose else ""),
                {"decision": "call_tool", "tool": tool},
            )
            if tool not in rec.selected_tools:
                rec.selected_tools.append(tool)
            reasoning.append(f"Step {iterations}: use {tool}" + (f" to {purpose}" if purpose else ""))
            return {
                "next_step": "call_tool",
                "iterations": iterations,
                "reasoning": reasoning,
                "pending_call": ToolCall(tool=tool, arguments=args, purpose=purpose),
            }
        answer = str(decision.get("answer") or "").strip()
        rec.finish_step(
            step, "success", "Decided to answer" + (f": {purpose}" if purpose else ""), {"decision": "final_answer"}
        )
        reasoning.append(f"Step {iterations}: ready to answer")
        return {
            "next_step": "final_answer",
            "iterations": iterations,
            "reasoning": reasoning,
            "pending_call": None,
            "draft_answer": answer or None,
        }

    # ---------------------------------------------------------------- validate
    async def validate(self, state: AgentState) -> AgentState:
        call = state.get("pending_call")
        rec = self.ctx.recorder
        assert call is not None
        tool_name = call["tool"]
        reason: str | None = None
        if tool_name not in self.tools:
            reason = (
                f"Tool '{tool_name}' is not enabled for this request; it was not executed."
                if tool_name in {t.value for t in ALL_TOOLS}
                else f"Unknown tool '{tool_name}'."
            )
        elif state.get("tool_calls", 0) >= self.settings.agent_max_tool_calls:
            reason = f"Tool-call limit ({self.settings.agent_max_tool_calls}) reached."
        else:
            try:
                parsed = self.tools[tool_name].args_model.model_validate(call["arguments"])
            except ValidationError as exc:
                first = exc.errors()[0]
                reason = f"Invalid arguments for {tool_name}: {'.'.join(map(str, first['loc']))} {first['msg']}"
            else:
                key = f"{tool_name}:{json.dumps(parsed.model_dump(), sort_keys=True)}"
                if key in self._seen_calls:
                    reason = "Duplicate call with identical arguments; skipped."
                else:
                    self._seen_calls.add(key)
                    call["arguments"] = parsed.model_dump(exclude_none=True)
                    return {"pending_call": call, "next_step": "call_tool"}
        rec.record_rejected(tool_name, call.get("purpose"), json.dumps(call.get("arguments"))[:200], reason)
        rec.warnings.append(reason)
        results = [
            *state.get("tool_results", []),
            {
                "tool": tool_name,
                "arguments": call["arguments"],
                "status": "rejected",
                "summary": reason,
                "observation": reason,
            },
        ]
        limit_hit = state.get("tool_calls", 0) >= self.settings.agent_max_tool_calls
        return {"tool_results": results, "pending_call": None, "next_step": "limit" if limit_hit else "validate_failed"}

    # ----------------------------------------------------------------- execute
    async def execute(self, state: AgentState) -> AgentState:
        call = state["pending_call"]
        assert call is not None
        tool = self.tools[call["tool"]]
        args = tool.args_model.model_validate(call["arguments"])
        output = await run_tool(
            self.ctx,
            tool,
            args,
            purpose=call["purpose"] or f"Run {tool.name.value}",
            timeout_s=self.settings.agent_tool_timeout_s,
            raise_errors=False,
        )
        tool_calls = state.get("tool_calls", 0) + 1
        if output is None:
            last = self.ctx.recorder.steps[-1]
            record = {
                "tool": call["tool"],
                "arguments": call["arguments"],
                "status": last.status,
                "summary": last.result_summary or "failed",
                "observation": f"Tool failed: {last.result_summary}",
            }
        else:
            if output.evidence:
                self.evidence.extend(register_evidence(self.ctx.recorder, output.evidence))
            observation = output.observation
            if output.evidence:
                ids = [e.source.id for e in output.evidence]
                observation = f"(evidence ids {ids[0]}-{ids[-1]})\n{observation}"
            record = {
                "tool": call["tool"],
                "arguments": call["arguments"],
                "status": output.status,
                "summary": output.summary,
                "observation": bound(observation, self.settings.tool_output_max_chars),
            }
        return {
            "tool_calls": tool_calls,
            "pending_call": None,
            "tool_results": [*state.get("tool_results", []), record],
        }

    # ----------------------------------------------------------------- observe
    async def observe(self, state: AgentState) -> AgentState:
        last = state["tool_results"][-1]
        reasoning = [*state.get("reasoning", []), f"Observed {last['tool']}: {last['summary']}"]
        if state.get("tool_calls", 0) >= self.settings.agent_max_tool_calls:
            self.ctx.recorder.warnings.append(
                f"Reached the maximum of {self.settings.agent_max_tool_calls} tool calls."
            )
            return {"reasoning": reasoning, "next_step": "limit", "evidence_count": len(self.evidence)}
        return {"reasoning": reasoning, "next_step": "validate_failed", "evidence_count": len(self.evidence)}

    # -------------------------------------------------------------- synthesize
    async def synthesize(self, state: AgentState) -> AgentState:
        rec = self.ctx.recorder
        results = state.get("tool_results", [])
        draft = state.get("draft_answer")
        if not results and draft:
            # The planner answered directly and no tool was needed.
            rec.delta(draft)
            return {"final_answer": draft}
        notes = []
        for r in results:
            if r["status"] != "success":
                notes.append(f"- {r['tool']}: {r['status']} ({r['summary']})")
            elif r["tool"] == "calculator":
                notes.append(f"- calculator: {r['summary']}")
        unavailable = state.get("unavailable_tools", [])
        parts = []
        if self.evidence:
            parts.append("Evidence:\n" + format_evidence(self.evidence, self.settings.evidence_max_chars))
        else:
            parts.append("Evidence: none was retrieved.")
        if notes:
            parts.append("Tool notes:\n" + "\n".join(notes))
        parts.append(f"Tools disabled by the user: {', '.join(unavailable) or 'none'}.")
        parts.append(f"Question: {state['question']}\n\nFinal answer:")
        history = [ChatMessage(m["role"], m["content"]) for m in state.get("history", [])][-6:]
        messages = [ChatMessage("system", AGENT_SYNTHESIZE_SYSTEM), *history, ChatMessage("user", "\n\n".join(parts))]
        text = await stream_llm(self.ctx, messages, self.ctx.llm_options(), purpose="Synthesize the final answer")
        return {"final_answer": text}

    # ------------------------------------------------------- validate citations
    async def validate_citations(self, state: AgentState) -> AgentState:
        finalize_answer(self.ctx, state.get("final_answer", ""))
        return {"final_answer": self.ctx.recorder.answer}

    # ----------------------------------------------------------------- routing
    @staticmethod
    def route_after_decide(state: AgentState) -> str:
        step = state.get("next_step")
        if step == "call_tool":
            return "validate"
        if step == "validate_failed":
            return "decide"
        return "synthesize"

    @staticmethod
    def route_after_validate(state: AgentState) -> str:
        step = state.get("next_step")
        if step == "call_tool":
            return "execute"
        if step == "limit":
            return "synthesize"
        return "decide"

    @staticmethod
    def route_after_observe(state: AgentState) -> str:
        return "synthesize" if state.get("next_step") == "limit" else "decide"
