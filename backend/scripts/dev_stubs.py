"""Development stubs for the Ollama and SearXNG HTTP APIs (UI development and smoke tests only).

The Ollama stub is NOT a language model. It returns deterministic, rule-based responses so the full
stack (streaming, tool selection, citations, SQL validation) can be exercised on machines
where Ollama is not installed. The backend talks to it exactly as it talks to Ollama.

The SearXNG stub returns a fixed list of real public URLs with made-up snippets labelled as
stub data; pages are still fetched (or refused) by the real SSRF-guarded fetcher.

    python scripts/dev_stubs.py --port 11435
    OLLAMA_BASE_URL=http://localhost:11435 OLLAMA_MODEL=fake-llm SEARXNG_URL=http://localhost:11435 \
        uvicorn app.main:app
"""

from __future__ import annotations

import argparse
import json
import re
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

MODEL = "fake-llm"
app = FastAPI()


def _decide(prompt: str) -> dict:
    question = prompt.rsplit("User question:", 1)[-1].split("\n")[0].strip()
    q = question.lower()
    done = "Observations so far" in prompt
    available = prompt.split("Available tools", 1)[-1].split("Unavailable tools", 1)[0]
    final = {"action": "final_answer", "tool": "none", "arguments": {}, "purpose": "Enough information gathered"}
    if done:
        if (
            "document_retrieval" in available
            and "web_search" in available
            and "compare" in q
            and "web_search(" not in prompt
        ):
            return {
                "action": "call_tool",
                "tool": "web_search",
                "arguments": {"query": question},
                "purpose": "Find recent public guidance",
            }
        return final
    math = re.search(r"(\d[\d\s+\-*/().]*[+\-*/][\d\s+\-*/().]*\d)", question)
    if math and "calculator" in available:
        return {
            "action": "call_tool",
            "tool": "calculator",
            "arguments": {"expression": math.group(1).strip()},
            "purpose": "Compute the arithmetic exactly",
        }
    if any(w in q for w in ("sales", "selling", "revenue", "orders", "customers", "product")):
        tool = "sql_query"
        args = {"question": question}
    elif any(w in q for w in ("uploaded", "policy", "document", "handbook", "my ")):
        tool, args = "document_retrieval", {"query": question}
    elif any(w in q for w in ("recent", "latest", "news", "current")):
        tool, args = "web_search", {"query": question}
    else:
        return {**final, "answer": f"(fake model) I would answer “{question}” from general knowledge."}
    return {"action": "call_tool", "tool": tool, "arguments": args, "purpose": f"Use {tool} for this question"}


def _sql(prompt: str) -> dict:
    q = prompt.rsplit("Question:", 1)[-1].lower()
    if "revenue" in q and "year" in q:
        sql = "SELECT substr(month, 1, 4) AS year, ROUND(SUM(revenue), 2) AS revenue FROM monthly_sales GROUP BY year"
    elif "country" in q:
        sql = "SELECT country, COUNT(*) AS customers FROM customers GROUP BY country ORDER BY customers DESC LIMIT 5"
    elif "delete" in q or "drop" in q:
        sql = "DELETE FROM orders"
    else:
        sql = (
            "SELECT p.name, SUM(m.units_sold) AS units FROM monthly_sales m JOIN products p ON p.id = m.product_id "
            "GROUP BY p.name ORDER BY units DESC LIMIT 5"
        )
    return {"sql": sql, "explanation": "Rule-based query from the fake model"}


def _answer(messages: list[dict]) -> str:
    system = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
    user = messages[-1]["content"]
    if "planning step" in system:
        return json.dumps(_decide(user))
    if "translate questions" in system:
        return json.dumps(_sql(user))
    ids = re.findall(r'<evidence id="(\d+)"', user)
    if ids:
        first = re.search(r'<evidence id="1"[^>]*>\n(.*?)\n</evidence>', user, re.S)
        snippet = " ".join((first.group(1) if first else "").split())[:220]
        cites = "".join(f"[{i}]" for i in ids[:2])
        return (
            f"**Fake model answer** based on the retrieved evidence {cites}.\n\n"
            f"> {snippet}\n\nInference: this text was produced by the development stub, not a real LLM."
        )
    if "Evidence: none" in user or "Tool notes" in user:
        return "**Fake model answer.** " + user.split("Tool notes:")[-1].split("Tools disabled")[0].strip()
    return f"**Fake model answer** to: {user[:200]}\n\n```python\nprint('hello from the fake model')\n```"


@app.get("/healthz")
async def healthz() -> str:
    return "OK"


@app.get("/search")
async def search(q: str = "", format: str = "html") -> dict:  # noqa: A002
    if format != "json":
        return JSONResponse({"error": "json format required"}, status_code=403)
    results = [
        {
            "title": "What's New In Python (Python docs)",
            "url": "https://docs.python.org/3/whatsnew/index.html",
            "content": f"[stub snippet] Release notes for recent Python versions. Query: {q[:80]}",
            "engines": ["stub"],
        },
        {
            "title": "Python Insider: release announcements",
            "url": "https://pythoninsider.blogspot.com/",
            "content": "[stub snippet] Announcements of new Python releases and security fixes.",
            "engines": ["stub"],
        },
        {
            "title": "PEP 0 - Index of Python Enhancement Proposals",
            "url": "https://peps.python.org/",
            "content": "[stub snippet] The index of all Python Enhancement Proposals.",
            "engines": ["stub"],
        },
    ]
    return {"query": q, "results": results}


@app.get("/api/tags")
async def tags() -> dict:
    return {
        "models": [
            {
                "name": MODEL,
                "size": 1_000_000,
                "details": {"family": "stub", "parameter_size": "0B", "quantization_level": "none"},
            }
        ]
    }


@app.post("/api/chat")
async def chat(request: Request):  # noqa: ANN201
    body = await request.json()
    if body.get("model") != MODEL:
        return JSONResponse({"error": f"model '{body.get('model')}' not found, try pulling it first"}, status_code=404)
    text = _answer(body["messages"])
    if not body.get("stream", True):
        return {
            "model": MODEL,
            "message": {"role": "assistant", "content": text},
            "done": True,
            "prompt_eval_count": 100,
            "eval_count": len(text) // 4,
        }

    def gen():  # noqa: ANN202
        for i in range(0, len(text), 8):
            yield json.dumps({"model": MODEL, "message": {"content": text[i : i + 8]}, "done": False}) + "\n"
            time.sleep(0.01)
        yield (
            json.dumps(
                {
                    "model": MODEL,
                    "message": {"content": ""},
                    "done": True,
                    "prompt_eval_count": 100,
                    "eval_count": len(text) // 4,
                }
            )
            + "\n"
        )

    return StreamingResponse(gen(), media_type="application/x-ndjson")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=11435)
    uvicorn.run(app, host="127.0.0.1", port=parser.parse_args().port, log_level="warning")
