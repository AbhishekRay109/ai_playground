from app.core.errors import LLMUnavailable
from tests.conftest import SAMPLE_MD


def test_request_validation(client):
    r = client.post("/api/v1/chat", json={"question": "   ", "mode": "direct"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    r = client.post("/api/v1/chat", json={"question": "hi", "mode": "telepathy"})
    assert r.status_code == 422
    r = client.post("/api/v1/chat", json={"question": "hi", "mode": "agent", "enabled_tools": ["shell"]})
    assert r.status_code == 422
    r = client.post("/api/v1/chat", json={"question": "hi", "mode": "direct", "settings": {"temperature": 9}})
    assert r.status_code == 422
    r = client.post("/api/v1/chat", json={"question": "x" * 5000, "mode": "direct"})
    assert r.status_code == 422


def test_body_size_limit(client):
    r = client.post("/api/v1/chat", content=b"{" + b" " * 300_000 + b"}", headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_errors_do_not_leak_internals(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret internal path /etc/app")

    from fastapi.testclient import TestClient

    monkeypatch.setattr(client.app.state.container.sessions_repo, "list", boom)
    r = TestClient(client.app, raise_server_exceptions=False).get("/api/v1/sessions")
    assert r.status_code == 500
    assert "secret" not in r.text and r.json()["error"]["code"] == "internal_error"


def test_sessions_persist_and_delete(client, llm):
    llm.responder = lambda m: "Answer one."
    first = client.post("/api/v1/chat", json={"question": "First question here", "mode": "direct"}).json()
    sid = first["session_id"]
    client.post("/api/v1/chat", json={"question": "Second", "mode": "direct", "session_id": sid})
    sessions = client.get("/api/v1/sessions").json()
    assert sessions[0]["id"] == sid and sessions[0]["title"] == "First question here"
    assert sessions[0]["message_count"] == 4 and sessions[0]["last_mode"] == "direct"
    detail = client.get(f"/api/v1/sessions/{sid}").json()
    roles = [m["role"] for m in detail["messages"]]
    assert roles == ["user", "assistant", "user", "assistant"]
    meta = detail["messages"][1]["meta"]
    assert meta["mode"] == "direct" and meta["steps"] and "answer" not in meta
    # feedback
    msg_id = detail["messages"][1]["id"]
    assert client.post(f"/api/v1/messages/{msg_id}/feedback", json={"rating": 1}).status_code == 204
    assert client.get(f"/api/v1/sessions/{sid}").json()["messages"][1]["feedback"] == 1
    assert (
        client.post(f"/api/v1/messages/{detail['messages'][0]['id']}/feedback", json={"rating": 1}).status_code == 404
    )
    # delete
    assert client.delete(f"/api/v1/sessions/{sid}").status_code == 204
    assert client.get(f"/api/v1/sessions/{sid}").status_code == 404
    assert client.delete(f"/api/v1/sessions/{sid}").status_code == 404


def test_failed_request_is_persisted_as_error(client, llm):
    llm.fail_with = LLMUnavailable("down")
    r = client.post("/api/v1/chat", json={"question": "hi", "mode": "direct"})
    assert r.status_code == 503
    sid = client.get("/api/v1/sessions").json()[0]["id"]
    msgs = client.get(f"/api/v1/sessions/{sid}").json()["messages"]
    assert msgs[-1]["status"] == "error"


def test_document_endpoints(client):
    files = [
        ("files", ("policy.md", SAMPLE_MD.encode(), "text/markdown")),
        ("files", ("dup.md", SAMPLE_MD.encode(), "text/markdown")),
        ("files", ("virus.exe", b"MZ", "application/octet-stream")),
    ]
    results = client.post("/api/v1/documents", files=files).json()["results"]
    assert [r["status"] for r in results] == ["ready", "duplicate", "error"]
    docs = client.get("/api/v1/documents").json()
    assert len(docs) == 1 and docs[0]["filename"] == "policy.md" and docs[0]["stale"] is False
    assert client.delete(f"/api/v1/documents/{docs[0]['id']}").status_code == 204
    assert client.get("/api/v1/documents").json() == []
    assert client.delete("/api/v1/documents/nope").status_code == 404


def test_upload_file_count_limit(client, container):
    container.settings.max_files_per_upload = 1
    files = [("files", (f"{i}.txt", b"hello world", "text/plain")) for i in range(2)]
    r = client.post("/api/v1/documents", files=files)
    assert r.status_code == 422 and "Too many files" in r.json()["error"]["message"]


def test_health_and_models(client, llm):
    health = client.get("/api/v1/health").json()
    assert set(health["services"]) == {"llm", "web_search", "embeddings", "vector_store", "sql_demo_db"}
    assert health["services"]["llm"]["ok"] is False  # scripted model name differs from configured
    models = client.get("/api/v1/models").json()
    assert models["available"] and models["models"][0]["name"] == "scripted-test-model"
    llm.fail_with = LLMUnavailable("Ollama is not reachable.", hint="Start Ollama")
    models = client.get("/api/v1/models").json()
    assert models["available"] is False and models["hint"] == "Start Ollama"


def test_config_update_validates_models(client, llm):
    cfg = client.get("/api/v1/config").json()
    assert cfg["runtime"]["chat_model"] == "test-model"
    assert "secret" not in str(cfg).lower()
    r = client.put("/api/v1/config", json={"chat_model": "not-installed"})
    assert r.status_code == 422 and "ollama pull" in r.json()["error"]["hint"]
    r = client.put("/api/v1/config", json={"chat_model": "scripted-test-model", "temperature": 0.7, "rag_top_k": 8})
    assert r.status_code == 200
    rt = client.get("/api/v1/config").json()["runtime"]
    assert rt["chat_model"] == "scripted-test-model" and rt["temperature"] == 0.7 and rt["rag_top_k"] == 8
    assert client.put("/api/v1/config", json={"temperature": 5}).status_code == 422
    r = client.put("/api/v1/config", json={"embedding_model": "hash-128"})
    assert r.status_code == 200 and r.json()["warnings"]
    reset = client.post("/api/v1/config/reset").json()
    assert reset["runtime"]["chat_model"] == "test-model"


def test_rate_limit(container):
    from fastapi.testclient import TestClient

    from app.main import create_app

    container.settings.rate_limit_per_minute = 2
    with TestClient(create_app(container=container)) as c:
        codes = [c.post("/api/v1/chat", json={"question": "hi", "mode": "direct"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_cors_configured_from_settings(client):
    r = client.options(
        "/api/v1/chat", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"}
    )
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
    r = client.options(
        "/api/v1/chat", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"}
    )
    assert "access-control-allow-origin" not in r.headers
