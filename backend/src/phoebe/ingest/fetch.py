"""SSRF-safe fetcher for user-supplied links.

Phoebe is a public demo, so any visitor can submit a URL; this module is a
security boundary. Every hop (the initial URL and each redirect target) is
validated: https only, no userinfo, port 443 only, and every resolved address
must be globally routable (private, loopback, link-local, reserved, multicast
and unspecified ranges are refused, IPv4-mapped IPv6 is unwrapped first).
Redirects are followed manually, at most ``MAX_REDIRECTS``. The body is
streamed and capped at ``MAX_BODY_BYTES``, and only allowlisted content types
are accepted.

Known limitation, accepted for the demo: DNS can change between our check and
the connection httpx makes (TOCTOU / DNS rebinding). The Lambda runs outside a
VPC, so no private network is reachable from it anyway.

Error messages are user-facing reasons and never include resolved addresses.
"""

import codecs
import ipaddress
import re
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

MAX_REDIRECTS = 3
MAX_BODY_BYTES = 2 * 1024 * 1024
TIMEOUT_S = 10.0
ALLOWED_CONTENT_TYPES = frozenset({"text/html", "text/plain", "text/markdown"})
USER_AGENT = "PhoebeDemoFetcher/1.0"
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

Resolver = Callable[[str], list[str]]


class UnsafeUrlError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class FetchError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class FetchedPage:
    final_url: str
    content_type: str
    text: str


def default_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def _is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or not ip.is_global
    )


def _check_address(raw: str) -> None:
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        raise UnsafeUrlError("Link points to a disallowed address") from None
    if _is_blocked(ip):
        raise UnsafeUrlError("Link points to a disallowed address")


def _validate(url: httpx.URL, resolver: Resolver) -> None:
    if url.scheme != "https":
        raise UnsafeUrlError("Only https links are allowed")
    # Use the exact ASCII (punycode) host httpx will connect to, so the address
    # we validate is the address we connect to.
    host = url.raw_host.decode("ascii")
    if not host:
        raise UnsafeUrlError("Link has no host")
    if url.userinfo:
        raise UnsafeUrlError("Links with credentials are not allowed")
    if url.port not in (None, 443):
        raise UnsafeUrlError("Only the standard https port is allowed")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        try:
            addresses = resolver(host)
        except OSError, UnicodeError:
            raise FetchError("Could not resolve host") from None
        if not addresses:
            raise FetchError("Could not resolve host")
        for address in addresses:
            _check_address(address)
    else:
        _check_address(host)


def _parse(raw: str) -> httpx.URL:
    try:
        return httpx.URL(raw)
    except httpx.InvalidURL:
        raise UnsafeUrlError("Link is not a valid URL") from None


def _decode(body: bytes, charset: str | None) -> str:
    if charset:
        try:
            codecs.lookup(charset)
            return body.decode(charset, errors="replace")
        except LookupError:
            pass
    return body.decode("utf-8", errors="replace")


def _read_page(
    response: httpx.Response, deadline: float, clock: Callable[[], float]
) -> FetchedPage:
    if not 200 <= response.status_code < 300:
        raise FetchError(f"Link returned HTTP {response.status_code}")
    encoding = response.headers.get("content-encoding", "identity").strip().lower()
    if encoding not in ("", "identity"):
        raise FetchError("Compressed responses are not supported")
    media_type = (
        response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    )
    if media_type not in ALLOWED_CONTENT_TYPES:
        raise FetchError("Unsupported content type")
    declared = response.headers.get("content-length")
    if declared is not None:
        declared = declared.strip()
        if declared.isascii() and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            raise FetchError("Page too large")
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        if clock() > deadline:
            raise FetchError("Link took too long")
        total += len(chunk)
        if total > MAX_BODY_BYTES:
            raise FetchError("Page too large")
        chunks.append(chunk)
    return FetchedPage(
        final_url=str(response.url),
        content_type=media_type,
        text=_decode(b"".join(chunks), response.charset_encoding),
    )


def fetch_url(
    url: str,
    *,
    resolver: Resolver = default_resolver,
    transport: httpx.BaseTransport | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> FetchedPage:
    current = _parse(url)
    deadline = clock() + TIMEOUT_S
    try:
        with httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(TIMEOUT_S),
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
        ) as client:
            redirects = 0
            while True:
                if clock() > deadline:
                    raise FetchError("Link took too long")
                _validate(current, resolver)
                with client.stream("GET", current) as response:
                    if response.status_code not in REDIRECT_STATUSES:
                        return _read_page(response, deadline, clock)
                    location = response.headers.get("location")
                if not location:
                    raise FetchError("Link redirected without a destination")
                if redirects >= MAX_REDIRECTS:
                    raise FetchError("Too many redirects")
                redirects += 1
                try:
                    current = current.join(location)
                except httpx.InvalidURL:
                    raise UnsafeUrlError("Link is not a valid URL") from None
    except httpx.HTTPError, httpx.StreamError, httpx.InvalidURL:
        raise FetchError("Could not fetch link") from None


_GOOGLE_DOC_PATH = re.compile(r"^/document/d/([A-Za-z0-9_-]+)(?:/|$)")


def google_doc_export_url(url: str) -> str | None:
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL:
        return None
    if parsed.scheme != "https" or parsed.host != "docs.google.com":
        return None
    match = _GOOGLE_DOC_PATH.match(parsed.path)
    if match is None:
        return None
    return f"https://docs.google.com/document/d/{match.group(1)}/export?format=txt"
