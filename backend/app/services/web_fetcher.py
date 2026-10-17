"""SSRF-hardened fetching of public web pages.

Protections:
* only ``http``/``https``, no credentials in URLs, optional domain allow/block lists;
* every hostname is resolved and *all* addresses must be public (no loopback, private,
  link-local, multicast, reserved or unspecified ranges); the connection is then made to
  the validated IP so DNS rebinding between check and connect is not possible;
* redirects are followed manually (bounded) and each hop is re-validated;
* time limits, byte limits and an HTML/text content-type allowlist;
* robots.txt is respected; 401/402/403/429 responses and login walls are not bypassed.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import time
import urllib.robotparser
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx
from bs4 import BeautifulSoup

from app.core.logging import get_logger

log = get_logger(__name__)

ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")


class FetchBlocked(Exception):
    """The URL is not allowed (SSRF guard, robots.txt, domain policy)."""


Resolver = Callable[[str, int], list[str]]


def default_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(info[4][0] for info in infos))


def is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip.split("%")[0])
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not (addr.is_multicast or addr.is_reserved or addr.is_unspecified)


def _domain_matches(host: str, domains: list[str]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == d.lower() or host.endswith("." + d.lower().lstrip(".")) for d in domains)


@dataclass
class UrlPolicy:
    allow_private: bool = False
    allowed_domains: tuple[str, ...] = ()
    blocked_domains: tuple[str, ...] = ()
    resolver: Resolver = default_resolver

    def check_url(self, url: str) -> tuple[str, int]:
        """Validate scheme/host/domain policy. Returns ``(host, port)``."""
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            raise FetchBlocked(f"scheme '{parts.scheme}' is not allowed")
        if parts.username or parts.password:
            raise FetchBlocked("credentials in URLs are not allowed")
        host = (parts.hostname or "").strip().lower()
        if not host:
            raise FetchBlocked("URL has no host")
        if host in ("localhost",) or host.endswith((".localhost", ".local", ".internal")):
            if not self.allow_private:
                raise FetchBlocked("local hostnames are not allowed")
        if self.blocked_domains and _domain_matches(host, list(self.blocked_domains)):
            raise FetchBlocked("domain is blocked by configuration")
        if self.allowed_domains and not _domain_matches(host, list(self.allowed_domains)):
            raise FetchBlocked("domain is not in the allowlist")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        return host, port

    def resolve_checked(self, host: str, port: int) -> list[str]:
        try:
            ipaddress.ip_address(host)
            ips = [host]
        except ValueError:
            try:
                ips = self.resolver(host, port)
            except OSError as exc:
                raise FetchBlocked(f"could not resolve host '{host}'") from exc
        if not ips:
            raise FetchBlocked(f"could not resolve host '{host}'")
        if not self.allow_private:
            for ip in ips:
                if not is_public_ip(ip):
                    raise FetchBlocked(f"host '{host}' resolves to a non-public address")
        return ips


class _GuardedBackend(httpcore.AsyncNetworkBackend):
    """Network backend that validates the destination IP at connect time."""

    def __init__(self, policy: UrlPolicy) -> None:
        self._policy = policy
        self._inner = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ):  # noqa: ANN201
        ips = await asyncio.to_thread(self._policy.resolve_checked, host, port)
        # Connect to the validated IP; TLS SNI/certificate checks still use the hostname.
        return await self._inner.connect_tcp(
            ips[0], port, timeout=timeout, local_address=local_address, socket_options=socket_options
        )

    async def connect_unix_socket(self, *args: Any, **kwargs: Any):  # noqa: ANN201
        raise FetchBlocked("unix sockets are not allowed")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class GuardedTransport(httpx.AsyncHTTPTransport):
    def __init__(self, policy: UrlPolicy) -> None:
        super().__init__(trust_env=False)
        # Replace the connection pool with one using the guarded network backend.
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(), network_backend=_GuardedBackend(policy)
        )


@dataclass
class FetchedPage:
    url: str  # URL requested
    final_url: str
    ok: bool
    status: str  # ok | blocked | robots_disallowed | http_<code> | timeout | unsupported_type | error
    title: str = ""
    text: str = ""
    truncated: bool = False
    latency_ms: int = 0
    error: str | None = None


_WS_RE = re.compile(r"[ \t ]+")


def html_to_text(html: str) -> tuple[str, str]:
    """Extract ``(title, main_text)`` from HTML. Tolerates broken markup."""
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.get_text(" ", strip=True) if soup.title else "")[:300]
    for tag in soup(
        [
            "script",
            "style",
            "noscript",
            "svg",
            "iframe",
            "form",
            "nav",
            "footer",
            "header",
            "aside",
            "button",
            "template",
            "object",
            "embed",
        ]
    ):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    text = root.get_text("\n", strip=True)
    lines = [_WS_RE.sub(" ", ln).strip() for ln in text.split("\n")]
    # Drop very short navigation-like lines but keep paragraph structure.
    lines = [ln for ln in lines if len(ln) > 2]
    return title, "\n".join(lines)


class WebFetcher:
    def __init__(
        self,
        policy: UrlPolicy,
        *,
        timeout_s: float,
        max_bytes: int,
        max_redirects: int,
        user_agent: str,
        respect_robots: bool,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.policy = policy
        self.timeout_s = timeout_s
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.user_agent = user_agent
        self.respect_robots = respect_robots
        self._transport = transport
        self._robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _client(self) -> httpx.AsyncClient:
        transport = self._transport or GuardedTransport(self.policy)
        return httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(self.timeout_s),
            follow_redirects=False,
            headers={"User-Agent": self.user_agent, "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8"},
            trust_env=False,
        )

    async def _robots_allowed(self, client: httpx.AsyncClient, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots_cache:
            parser: urllib.robotparser.RobotFileParser | None = None
            try:
                self.policy.check_url(origin + "/robots.txt")
                resp = await client.get(origin + "/robots.txt")
                if resp.status_code == 200 and len(resp.content) < 512_000:
                    parser = urllib.robotparser.RobotFileParser()
                    parser.parse(resp.text.splitlines())
            except (httpx.HTTPError, FetchBlocked):
                parser = None  # robots.txt unavailable: treat as allowed
            self._robots_cache[origin] = parser
        parser = self._robots_cache[origin]
        return True if parser is None else parser.can_fetch(self.user_agent, url)

    async def fetch(self, url: str) -> FetchedPage:
        start = time.perf_counter()

        def done(**kw: Any) -> FetchedPage:
            return FetchedPage(url=url, latency_ms=int((time.perf_counter() - start) * 1000), **kw)

        current = url
        try:
            async with self._client() as client:
                for _hop in range(self.max_redirects + 1):
                    host, port = self.policy.check_url(current)
                    # Resolve early for a clear error message (connect-time check is authoritative).
                    await asyncio.to_thread(self.policy.resolve_checked, host, port)
                    if self.respect_robots and not await self._robots_allowed(client, current):
                        return done(
                            final_url=current,
                            ok=False,
                            status="robots_disallowed",
                            error="robots.txt disallows fetching this page",
                        )
                    async with client.stream("GET", current) as resp:
                        if resp.is_redirect:
                            location = resp.headers.get("location")
                            if not location:
                                return done(
                                    final_url=current, ok=False, status="error", error="redirect without location"
                                )
                            current = urljoin(current, location)
                            continue
                        if resp.status_code in (401, 402, 403, 407, 429, 451):
                            return done(
                                final_url=current,
                                ok=False,
                                status=f"http_{resp.status_code}",
                                error="access restricted (not bypassed)",
                            )
                        if resp.status_code >= 400:
                            return done(
                                final_url=current,
                                ok=False,
                                status=f"http_{resp.status_code}",
                                error=f"HTTP {resp.status_code}",
                            )
                        ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                        if ctype and not ctype.startswith(ALLOWED_CONTENT_TYPES):
                            return done(
                                final_url=current,
                                ok=False,
                                status="unsupported_type",
                                error=f"unsupported content type {ctype}",
                            )
                        buf = bytearray()
                        truncated = False
                        async for chunk in resp.aiter_bytes():
                            buf.extend(chunk)
                            if len(buf) > self.max_bytes:
                                truncated = True
                                del buf[self.max_bytes :]
                                break
                        encoding = resp.charset_encoding or "utf-8"
                        raw = buf.decode(encoding, errors="replace")
                    if ctype == "text/plain":
                        title, text = "", raw
                    else:
                        title, text = await asyncio.to_thread(html_to_text, raw)
                    return done(final_url=current, ok=True, status="ok", title=title, text=text, truncated=truncated)
                return done(final_url=current, ok=False, status="error", error="too many redirects")
        except FetchBlocked as exc:
            return done(final_url=current, ok=False, status="blocked", error=str(exc))
        except httpx.TimeoutException:
            return done(final_url=current, ok=False, status="timeout", error=f"timed out after {self.timeout_s:.0f}s")
        except httpx.HTTPError as exc:
            return done(final_url=current, ok=False, status="error", error=type(exc).__name__)
        except Exception as exc:  # noqa: BLE001 - parsing errors etc. must not break the request
            log.warning("fetch failed error=%s", type(exc).__name__)
            return done(final_url=current, ok=False, status="error", error=type(exc).__name__)
