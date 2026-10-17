import httpx
import pytest

from app.core.errors import SearchRateLimited, SearchUnavailable
from app.services.search_service import SearxngClient, select_passages
from app.services.web_fetcher import FetchBlocked, UrlPolicy, WebFetcher, html_to_text, is_public_ip
from tests.conftest import sse_events

ARTICLE = """<html><head><title>Python 3.14 released</title><script>alert('x')</script></head>
<body><nav>Home | About</nav><article><h1>Python 3.14</h1>
<p>Python 3.14 was released in October 2025 with free-threading improvements and template strings.</p>
<p>The release also includes a new interpreter for faster startup.</p></article>
<footer>cookie banner</footer></body></html>"""


def public_resolver(host, port):
    return ["93.184.216.34"]


# ---------------------------------------------------------------- SSRF guards
@pytest.mark.parametrize(
    "ip,expected",
    [
        ("8.8.8.8", True),
        ("127.0.0.1", False),
        ("10.0.0.5", False),
        ("192.168.1.1", False),
        ("169.254.169.254", False),
        ("::1", False),
        ("fd00::1", False),
        ("0.0.0.0", False),
        ("::ffff:127.0.0.1", False),
        ("100.64.0.1", False),
    ],
)
def test_is_public_ip(ip, expected):
    assert is_public_ip(ip) is expected


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "gopher://example.com",
        "http://user:pw@example.com/",
        "http://localhost:8000/admin",
        "http://metadata.internal/",
        "http:///nohost",
    ],
)
def test_policy_rejects_dangerous_urls(url):
    with pytest.raises(FetchBlocked):
        UrlPolicy(resolver=public_resolver).check_url(url)


def test_policy_rejects_hosts_resolving_to_private_ips():
    policy = UrlPolicy(resolver=lambda h, p: ["10.1.2.3"])
    host, port = policy.check_url("https://looks-public.example/")
    with pytest.raises(FetchBlocked, match="non-public"):
        policy.resolve_checked(host, port)
    with pytest.raises(FetchBlocked):
        UrlPolicy().resolve_checked("169.254.169.254", 80)


def test_policy_domain_lists():
    policy = UrlPolicy(allowed_domains=("python.org",), blocked_domains=("evil.python.org",), resolver=public_resolver)
    policy.check_url("https://docs.python.org/3/")
    with pytest.raises(FetchBlocked):
        policy.check_url("https://evil.python.org/")
    with pytest.raises(FetchBlocked):
        policy.check_url("https://example.com/")


def make_fetcher(handler, **kw) -> WebFetcher:
    return WebFetcher(
        UrlPolicy(resolver=public_resolver),
        timeout_s=2,
        max_bytes=kw.get("max_bytes", 100_000),
        max_redirects=3,
        user_agent="test",
        respect_robots=kw.get("robots", False),
        transport=httpx.MockTransport(handler),
    )


async def test_redirect_to_private_address_is_blocked():
    def handler(req):
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})

    page = await make_fetcher(handler).fetch("https://example.com/start")
    assert not page.ok and page.status == "blocked"


async def test_redirect_loop_bounded():
    def handler(req):
        return httpx.Response(302, headers={"location": str(req.url) + "x"})

    page = await make_fetcher(handler).fetch("https://example.com/a")
    assert page.status == "error" and "redirects" in page.error


async def test_access_restricted_pages_are_not_bypassed():
    page = await make_fetcher(lambda r: httpx.Response(403, text="captcha")).fetch("https://example.com/")
    assert page.status == "http_403" and "not bypassed" in page.error


async def test_timeout_and_content_type_and_size_limits():
    def slow(req):
        raise httpx.ReadTimeout("slow", request=req)

    assert (await make_fetcher(slow).fetch("https://example.com/")).status == "timeout"
    pdf = await make_fetcher(
        lambda r: httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF")
    ).fetch("https://example.com/f.pdf")
    assert pdf.status == "unsupported_type"
    big = await make_fetcher(
        lambda r: httpx.Response(200, headers={"content-type": "text/html"}, content=b"<p>" + b"a" * 5000 + b"</p>"),
        max_bytes=1000,
    ).fetch("https://example.com/big")
    assert big.ok and big.truncated


async def test_robots_txt_is_respected():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private")
        return httpx.Response(200, headers={"content-type": "text/html"}, text=ARTICLE)

    fetcher = make_fetcher(handler, robots=True)
    assert (await fetcher.fetch("https://example.com/private/page")).status == "robots_disallowed"
    assert (await fetcher.fetch("https://example.com/public")).ok


def test_html_to_text_strips_boilerplate_and_handles_bad_html():
    title, text = html_to_text(ARTICLE)
    assert title == "Python 3.14 released"
    assert "free-threading" in text and "alert" not in text and "cookie banner" not in text
    assert html_to_text("<p>unclosed <b>tags <div>still works")[1]


def test_select_passages_prefers_relevant_paragraphs():
    text = (
        "Unrelated paragraph about the weather today and tomorrow.\n"
        "Python 3.14 introduces template strings for safer string processing.\n"
        "Another unrelated paragraph about cooking pasta at home."
    )
    out = select_passages(text, "What is new in Python 3.14?", max_chars=100)
    assert out.startswith("Python 3.14")


# ------------------------------------------------------------- SearXNG client
async def test_searxng_unavailable_and_rate_limited():
    def down(req):
        raise httpx.ConnectError("refused", request=req)

    with pytest.raises(SearchUnavailable) as exc:
        await SearxngClient("http://sx", 2, httpx.MockTransport(down)).search("q", 3)
    assert "SearXNG" in exc.value.hint
    with pytest.raises(SearchRateLimited):
        await SearxngClient("http://sx", 2, httpx.MockTransport(lambda r: httpx.Response(429))).search("q", 3)
    with pytest.raises(SearchUnavailable, match="refused the JSON"):
        await SearxngClient("http://sx", 2, httpx.MockTransport(lambda r: httpx.Response(403))).search("q", 3)


async def test_searxng_results_parsed_and_deduplicated():
    data = {
        "results": [
            {
                "title": "A",
                "url": "https://a.example/1",
                "content": "snippet a",
                "engines": ["duckduckgo"],
                "publishedDate": "2025-10-07",
            },
            {"title": "A dup", "url": "https://a.example/1", "content": "dup"},
            {"title": "Bad", "url": "javascript:alert(1)", "content": "x"},
            {"title": "B", "url": "https://b.example/2", "content": "snippet b"},
        ]
    }
    results = await SearxngClient("http://sx", 2, httpx.MockTransport(lambda r: httpx.Response(200, json=data))).search(
        "q", 5
    )
    assert [r.url for r in results] == ["https://a.example/1", "https://b.example/2"]
    assert results[0].engine == "duckduckgo" and results[0].published_date == "2025-10-07"
    assert results[1].published_date is None


# -------------------------------------------------------------- web mode (API)
def _setup_results(web):
    web.search_results = [
        {"title": "Python 3.14 released", "url": "https://news.example/py314", "content": "Python 3.14 is out."},
        {"title": "Blocked page", "url": "https://blocked.example/x", "content": "Snippet about Python releases."},
    ]
    web.pages["https://news.example/py314"] = httpx.Response(200, headers={"content-type": "text/html"}, text=ARTICLE)
    web.pages["https://blocked.example/x"] = httpx.Response(403, text="denied")


def test_web_mode_answers_with_real_urls_only(client, web, llm):
    _setup_results(web)
    llm.responder = lambda m: "Python 3.14 added template strings [1]. Also see [2] and [5]."
    data = client.post("/api/v1/chat", json={"question": "What changed in Python 3.14?", "mode": "web_search"}).json()
    assert data["status"] == "success"
    urls = [s["url"] for s in data["sources"]]
    assert urls == ["https://news.example/py314", "https://blocked.example/x"]
    assert data["sources"][0]["content_type"] == "page"
    assert data["sources"][1]["content_type"] == "snippet"  # page fetch was refused → snippet only
    assert "[5]" not in data["answer"] and data["citations"]["invalid_markers"] == [5]
    step = next(s for s in data["steps"] if s["name"] == "web_search")
    statuses = {r["url"]: r["fetch_status"] for r in step["details"]["results"]}
    assert statuses["https://blocked.example/x"] == "http_403"
    assert data["counts"]["web_sources"] == 2
    assert data["executed_tools"] == ["web_search"]


def test_web_mode_reports_searxng_unavailable(client, web):
    web.search_error = httpx.ConnectError("refused")
    resp = client.post("/api/v1/chat", json={"question": "news?", "mode": "web_search"})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "search_unavailable"


def test_web_mode_stream_error_event(client, web):
    web.search_error = httpx.ConnectError("refused")
    resp = client.post("/api/v1/chat/stream", json={"question": "news?", "mode": "web_search"})
    events = sse_events(resp.text)
    assert events[-1]["type"] == "error" and events[-1]["error"]["code"] == "search_unavailable"
    tool_end = [e for e in events if e["type"] == "tool_end"][0]
    assert tool_end["step"]["status"] == "error"


# ------------------------------------------------- real transport (local socket)
async def test_guarded_transport_connects_to_validated_ip_only():
    """Exercise the real GuardedTransport against a local HTTP server."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = b"<html><title>local</title><body><p>hello from the local test server</p></body></html>"
            self.send_response(200)
            self.send_header("content-type", "text/html")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        # The hostname "looks public" but resolves to loopback: blocked before any connection.
        blocked = WebFetcher(
            UrlPolicy(resolver=lambda h, p: ["127.0.0.1"]),
            timeout_s=2,
            max_bytes=10_000,
            max_redirects=2,
            user_agent="t",
            respect_robots=False,
        )
        page = await blocked.fetch(f"http://rebind.example:{port}/")
        assert page.status == "blocked"
        # With private networks explicitly allowed, the guarded backend connects to the resolved IP.
        allowed = WebFetcher(
            UrlPolicy(allow_private=True, resolver=lambda h, p: ["127.0.0.1"]),
            timeout_s=2,
            max_bytes=10_000,
            max_redirects=2,
            user_agent="t",
            respect_robots=False,
        )
        page = await allowed.fetch(f"http://rebind.example:{port}/")
        assert page.ok and page.title == "local"
    finally:
        server.shutdown()
