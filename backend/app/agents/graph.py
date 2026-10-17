"""LangGraph workflow for Agent Mode.

```
START → analyze → decide ─┬─(call_tool)→ validate ─┬─(ok)→ execute → observe ─┬→ decide
                          │                        ├─(rejected)→ decide       └→ synthesize
                          │                        └─(limit)→ synthesize
                          └─(final_answer | limit)→ synthesize → validate_citations → END
```
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agents.nodes import AgentNodes
from app.agents.state import AgentState
from app.schemas.chat import ExecutionStep
from app.services.modes.common import ModeContext
from app.tools.registry import enabled_tools


def build_graph(nodes: AgentNodes):  # noqa: ANN201
    g = StateGraph(AgentState)
    g.add_node("analyze", nodes.analyze)
    g.add_node("decide", nodes.decide)
    g.add_node("validate", nodes.validate)
    g.add_node("execute", nodes.execute)
    g.add_node("observe", nodes.observe)
    g.add_node("synthesize", nodes.synthesize)
    g.add_node("validate_citations", nodes.validate_citations)
    g.add_edge(START, "analyze")
    g.add_edge("analyze", "decide")
    g.add_conditional_edges(
        "decide", nodes.route_after_decide, {"validate": "validate", "decide": "decide", "synthesize": "synthesize"}
    )
    g.add_conditional_edges(
        "validate", nodes.route_after_validate, {"execute": "execute", "decide": "decide", "synthesize": "synthesize"}
    )
    g.add_edge("execute", "observe")
    g.add_conditional_edges("observe", nodes.route_after_observe, {"decide": "decide", "synthesize": "synthesize"})
    g.add_edge("synthesize", "validate_citations")
    g.add_edge("validate_citations", END)
    return g.compile()


async def run_agent(ctx: ModeContext) -> None:
    tools = enabled_tools(ctx.request.enabled_tools)
    ctx.recorder.available_tools = list(tools)
    nodes = AgentNodes(ctx, tools)
    graph = build_graph(nodes)
    s = ctx.container.settings
    initial: AgentState = {
        "question": ctx.request.question,
        "history": [{"role": m.role, "content": m.content} for m in ctx.history],
        "available_tools": list(tools),
    }
    # Each iteration visits at most 4 nodes; the recursion limit is a second safety net.
    final = await graph.ainvoke(initial, config={"recursion_limit": s.agent_max_iterations * 5 + 10})
    reasoning = final.get("reasoning", [])
    if reasoning:
        ctx.recorder.steps.append(
            ExecutionStep(
                id="summary",
                kind="system",
                name="execution_summary",
                status="success",
                purpose="Concise execution summary",
                result_summary=" · ".join(reasoning)[:1000],
            )
        )
