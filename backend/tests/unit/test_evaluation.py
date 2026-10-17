import json

from app.evaluation import metrics as m
from app.evaluation.runner import DatasetRunRequest, list_datasets, report_markdown, run_dataset


def test_metric_helpers():
    resp = {
        "steps": [
            {
                "name": "document_retrieval",
                "status": "success",
                "details": {
                    "chunks": [
                        {"chunk_id": "a", "text": "Book at least 21 days ahead."},
                        {"chunk_id": "b", "text": "Other"},
                    ]
                },
            }
        ],
        "citations": {"total_markers": 4, "valid_markers": 3},
        "executed_tools": ["document_retrieval"],
        "sources": [],
    }
    assert m.retrieval_hit(resp, ["21 days"]) is True
    assert m.retrieval_hit(resp, ["30 days"]) is False
    assert m.recall_at_k(resp, {"a", "c"}) == 0.5
    assert m.citation_validity(resp) == 0.75
    assert m.completeness_estimate("Book 21 days early", ["21 days", "director"]) == 0.5
    assert m.tool_selection_success(resp, ["document_retrieval"], ["web_search"]) is True
    assert m.tool_selection_success(resp, ["sql_query"], None) is False
    assert m.groundedness_estimate("Employees must book at least 21 days ahead.", "book at least 21 days ahead") == 1.0
    assert m.percentile([1, 2, 3, 4, 100], 50) == 3


def test_datasets_listed():
    names = [d["name"] for d in list_datasets()]
    assert "default" in names


async def test_run_dataset_with_scripted_llm(container, llm):
    def respond(messages):
        sp = messages[0].content
        if "planning step" in sp:
            q = messages[-1].content
            if "129 * 347" in q and "Observations so far" not in q:
                return json.dumps(
                    {
                        "action": "call_tool",
                        "tool": "calculator",
                        "arguments": {"expression": "129 * 347"},
                        "purpose": "compute",
                    }
                )
            return json.dumps({"action": "final_answer", "tool": "none", "arguments": {}, "purpose": "done"})
        if "translate questions" in sp:
            return json.dumps({"sql": "SELECT 1", "explanation": "x"})
        return "The answer is 21 days [1]. 44763."

    llm.responder = respond
    report = await run_dataset(container, DatasetRunRequest(dataset="default"))
    assert len(report["items"]) == 12
    calc = next(r for r in report["items"] if r["id"] == "agent-calculator")
    assert calc["executed_tools"] == ["calculator"] and calc["tool_selection_success"] is True
    booking = next(r for r in report["items"] if r["id"] == "rag-booking")
    assert booking["retrieval_hit"] is True and booking["recall_at_k"] is not None
    assert 0 <= report["summary"]["retrieval_hit_rate"] <= 1
    md = report_markdown(report)
    assert "Retrieval hit rate" in md and "(estimate)" in md
    # Running again does not duplicate the fixture documents.
    await run_dataset(container, DatasetRunRequest(dataset="default", item_ids=["rag-booking"]))
    assert container.documents_repo.count() == 3


def test_compare_endpoint(client, llm):
    llm.responder = lambda msgs: "Paris."
    r = client.post(
        "/api/v1/evaluation/compare", json={"question": "Capital of France?", "modes": ["direct", "document_rag"]}
    )
    assert r.status_code == 200
    results = r.json()
    assert [x["mode"] for x in results] == ["direct", "document_rag"]
    assert results[0]["response"]["answer"] == "Paris."
    assert results[1]["response"]["executed_tools"] == ["document_retrieval"]
    # comparisons are not saved as sessions
    assert client.get("/api/v1/sessions").json() == []
