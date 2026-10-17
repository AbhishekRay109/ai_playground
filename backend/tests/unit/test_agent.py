import asyncio
import json

import httpx
import pytest

from app.schemas.chat import ChatRequest, Mode, ToolName
from app.services.chat_service import ChatService
from app.tools.calculator_tool import CalculatorError, safe_eval
from tests.conftest import SAMPLE_MD, planner

ALL = ["document_retrieval", "web_search", "sql_query", "calculator"]


def call(tool, **args):
    return {"action": "call_tool", "tool": tool, "arguments": args, "purpose": f"use {tool}"}


def ask(client, question, tools, **extra):
    resp = client.post("/api/v1/chat", json={"question": question, "mode": "agent", "enabled_tools": tools, **extra})
    assert resp.status_code == 200, resp.text
    return resp.json()


# ----------------------------------------------------------------- calculator
@pytest.mark.parametrize(
    "expr,value",
    [
        ("129 * 347", 44763),
        ("2 ** 10", 1024),
        ("(1 + 2) * 3 / 4", 2.25),
        ("sqrt(16) + round(2.6)", 7),
        ("-3 % 2", 1),
        ("2^3", 8),
    ],
)
def test_safe_eval(expr, value):
    assert safe_eval(expr) == value


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('ls')",
        "open('/etc/passwd')",
        "a + 1",
        "2 ** 100000",
        "1 / 0",
        "[1, 2]",
        "lambda: 1",
        "().__class__",
        "9" * 300,
    ],
)
def test_safe_eval_rejects(expr):
    with pytest.raises(CalculatorError):
        safe_eval(expr)


# ------------------------------------------------------------ tool selection
def test_agent_uses_calculator_and_trace_matches_execution(client, llm):
    llm.responder = planner([call("calculator", expression="129 * 347")], answer="129 × 347 = 44763.")
    data = ask(client, "What is 129 * 347?", ALL)
    assert data["executed_tools"] == ["calculator"]
    assert data["selected_tools"] == ["calculator"]
    assert data["available_tools"] == ALL
    calc = next(s for s in data["steps"] if s["name"] == "calculator")
    assert calc["status"] == "success" and calc["details"]["result"] == 44763
    assert "44763" in data["answer"]


def test_agent_answers_directly_without_tools(client, llm):
    llm.responder = planner(
        [
            {
                "action": "final_answer",
                "tool": "none",
                "arguments": {},
                "purpose": "general knowledge",
                "answer": "Hello there!",
            }
        ]
    )
    data = ask(client, "Say hello", ALL)
    assert data["executed_tools"] == [] and data["answer"] == "Hello there!"


def test_disabled_tool_is_never_executed(client, llm, web):
    web.search_results = [{"title": "x", "url": "https://x.example", "content": "y"}]
    llm.responder = planner(
        [call("web_search", query="python news")], answer="Web search is disabled, so I cannot look that up."
    )
    data = ask(client, "What changed recently in the Python ecosystem?", ["calculator"])
    assert data["executed_tools"] == []
    assert data["selected_tools"] == ["web_search"]
    rejected = [s for s in data["steps"] if s["status"] == "rejected"]
    assert rejected and rejected[0]["name"] == "web_search"
    assert "not enabled" in rejected[0]["result_summary"]
    assert not any("searxng" in u or "x.example" in u for u in web.requests)
    # The planner's JSON schema only offered the enabled tool.
    planner_call = next(c for c in llm.calls if "planning step" in c[0].content)
    assert (
        "Unavailable tools (disabled by the user, do not use): document_retrieval, web_search, sql_query"
        in planner_call[-1].content
    )


def test_unknown_tool_and_bad_arguments_are_rejected(client, llm):
    llm.responder = planner(
        [call("shell", cmd="rm -rf /"), call("calculator", wrong="x"), call("calculator", expression="2+2")], answer="4"
    )
    data = ask(client, "2+2?", ALL)
    statuses = [(s["name"], s["status"]) for s in data["steps"] if s["kind"] == "tool"]
    assert statuses == [("shell", "rejected"), ("calculator", "rejected"), ("calculator", "success")]
    assert data["executed_tools"] == ["calculator"]


def test_multi_tool_document_and_web(client, llm, web):
    client.post("/api/v1/documents", files=[("files", ("policy.md", SAMPLE_MD.encode(), "text/markdown"))])
    web.search_results = [
        {"title": "Gov guidance", "url": "https://gov.example/travel", "content": "Book 30 days ahead."}
    ]
    web.pages["https://gov.example/travel"] = httpx.Response(404)
    llm.responder = planner(
        [
            call("document_retrieval", query="international travel booking"),
            call("web_search", query="public travel booking guidance"),
        ],
        answer="The policy says 21 days [1] while public guidance says 30 days [3].",
    )
    data = ask(client, "Compare the uploaded policy with recent public guidance.", ALL)
    assert data["executed_tools"] == ["document_retrieval", "web_search"]
    kinds = [s["kind"] for s in data["sources"]]
    assert "document" in kinds and "web" in kinds
    assert [s["id"] for s in data["sources"]] == list(range(1, len(data["sources"]) + 1))
    web_src = next(s for s in data["sources"] if s["kind"] == "web")
    assert web_src["url"] == "https://gov.example/travel"
    assert data["counts"]["web_sources"] == 1 and data["counts"]["retrieved_chunks"] >= 1


def test_tool_call_limit(client, llm, container):
    container.settings.agent_max_tool_calls = 2
    llm.responder = planner([call("calculator", expression=f"{i}+1") for i in range(10)], answer="done")
    data = ask(client, "count", ALL)
    executed = [s for s in data["steps"] if s["name"] == "calculator" and s["status"] == "success"]
    assert len(executed) == 2
    assert any("maximum of 2 tool calls" in w for w in data["warnings"])


def test_iteration_limit_with_repeated_invalid_decisions(client, llm, container):
    container.settings.agent_max_iterations = 3
    llm.responder = planner([call("web_search", query="x")] * 10, answer="Stopped.")
    data = ask(client, "loop forever", ["calculator"])
    planner_steps = [s for s in data["steps"] if s["name"] == "planner"]
    assert len(planner_steps) == 3
    assert data["executed_tools"] == []
    assert any("maximum of 3 iterations" in w for w in data["warnings"])


def test_duplicate_calls_are_skipped(client, llm):
    llm.responder = planner([call("calculator", expression="1+1"), call("calculator", expression="1+1")], answer="2")
    data = ask(client, "1+1", ALL)
    statuses = [s["status"] for s in data["steps"] if s["name"] == "calculator"]
    assert statuses == ["success", "rejected"]


def test_invalid_planner_output_is_bounded(client, llm):
    llm.responder = lambda m: "not json at all" if "planning step" in m[0].content else "fallback answer"
    data = ask(client, "anything", ALL)
    assert data["answer"] == "fallback answer"
    assert len([s for s in data["steps"] if s["name"] == "planner"]) == 2


async def test_tool_timeout_is_reported(container, llm, monkeypatch):
    from app.tools.calculator_tool import CalculatorTool

    async def slow_run(self, args, ctx):
        await asyncio.sleep(5)

    monkeypatch.setattr(CalculatorTool, "run", slow_run)
    container.settings.agent_tool_timeout_s = 0.1
    llm.responder = planner([call("calculator", expression="1+1")], answer="The calculator timed out.")
    resp = await ChatService(container).execute(
        ChatRequest(question="1+1", mode=Mode.AGENT, enabled_tools=[ToolName.CALCULATOR]), persist=False
    )
    calc = next(s for s in resp.steps if s.name == "calculator")
    assert calc.status == "timeout"
    assert resp.status == "partial"
    assert resp.errors[0]["code"] == "tool_timeout"
    assert resp.executed_tools == ["calculator"]


async def test_overall_request_timeout(container, llm):
    container.settings.agent_request_timeout_s = 0.2
    llm.delay_s = 1.0
    llm.responder = planner([])
    events = [
        e
        async for e in ChatService(container).stream(
            ChatRequest(question="slow", mode=Mode.AGENT, enabled_tools=[ToolName.CALCULATOR]), persist=False
        )
    ]
    assert events[-1]["type"] == "error" and events[-1]["error"]["code"] == "request_timeout"


async def test_cancellation_stops_the_run(container, llm):
    llm.delay_s = 2.0
    gen = ChatService(container).stream(ChatRequest(question="hi", mode=Mode.DIRECT))
    first = await gen.__anext__()
    assert first["type"] == "session"
    assert (await gen.__anext__())["type"] == "tool_start"  # the LLM step started
    task = asyncio.ensure_future(gen.__anext__())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    msgs = container.sessions_repo.get_with_messages(first["session_id"]).messages
    assert msgs[-1].status == "cancelled"


def test_planner_schema_restricts_tools(client, llm):
    seen = {}
    original = llm.chat

    async def spy(messages, options):
        if options.format:
            seen["schema"] = options.format
        return await original(messages, options)

    llm.chat = spy
    llm.responder = planner([], answer="ok")
    ask(client, "hello", ["calculator", "sql_query"])
    assert seen["schema"]["properties"]["tool"]["enum"] == ["calculator", "sql_query", "none"]
    assert json.dumps(seen["schema"])
