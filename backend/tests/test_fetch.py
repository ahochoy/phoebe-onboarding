import httpx
import pytest

from phoebe.ingest.fetch import (
    MAX_BODY_BYTES,
    FetchError,
    UnsafeUrlError,
    fetch_url,
    google_doc_export_url,
)

PUBLIC_IP = "93.184.216.34"


def public(host: str) -> list[str]:
    return [PUBLIC_IP]


def html_response(body: str = "<p>hi</p>", ctype: str = "text/html; charset=utf-8"):
    return httpx.Response(200, headers={"content-type": ctype}, content=body.encode())


def ok_transport() -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: html_response())


def redirect_transport(location: str, code: int = 302) -> httpx.MockTransport:
    return httpx.MockTransport(
        lambda request: httpx.Response(code, headers={"location": location})
    )


def loop_transport() -> httpx.MockTransport:
    return redirect_transport("https://loop.test/")


def big_transport(size: int, declare: bool = False) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        headers = {"content-type": "text/plain"}
        if declare:
            headers["content-length"] = str(size)
        return httpx.Response(200, headers=headers, content=b"a" * size)

    return httpx.MockTransport(handler)


def ctype_transport(ctype: str) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: html_response("x", ctype))


@pytest.mark.parametrize(
    "ip", ["127.0.0.1", "10.0.0.5", "169.254.169.254", "::1", "fd00::1", "0.0.0.0"]
)
def test_blocks_private_ips(ip):
    with pytest.raises(UnsafeUrlError):
        fetch_url(
            "https://evil.test/", resolver=lambda h: [ip], transport=ok_transport()
        )


def test_error_does_not_leak_ip():
    with pytest.raises(UnsafeUrlError) as exc:
        fetch_url(
            "https://evil.test/",
            resolver=lambda h: ["10.0.0.5"],
            transport=ok_transport(),
        )
    assert "10.0.0.5" not in exc.value.reason


def test_blocks_if_any_address_private():
    with pytest.raises(UnsafeUrlError):
        fetch_url(
            "https://mixed.test/",
            resolver=lambda h: [PUBLIC_IP, "10.0.0.5"],
            transport=ok_transport(),
        )


def test_blocks_ipv4_mapped_ipv6():
    with pytest.raises(UnsafeUrlError):
        fetch_url(
            "https://evil.test/",
            resolver=lambda h: ["::ffff:10.0.0.1"],
            transport=ok_transport(),
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/",
        "https://[::1]/",
        "https://[::ffff:10.0.0.1]/",
        "https://169.254.169.254/",
    ],
)
def test_blocks_ip_literals(url):
    def boom(host: str) -> list[str]:
        raise AssertionError("resolver must not be called for IP literals")

    with pytest.raises(UnsafeUrlError):
        fetch_url(url, resolver=boom, transport=ok_transport())


def test_public_ip_literal_allowed():
    page = fetch_url(
        "https://93.184.216.34/", resolver=lambda h: [], transport=ok_transport()
    )
    assert page.text == "<p>hi</p>"


def test_http_scheme_rejected():
    with pytest.raises(UnsafeUrlError, match="https"):
        fetch_url("http://example.com/", resolver=public)


def test_other_scheme_rejected():
    with pytest.raises(UnsafeUrlError):
        fetch_url("file:///etc/passwd", resolver=public)


def test_userinfo_rejected():
    with pytest.raises(UnsafeUrlError):
        fetch_url(
            "https://user:pass@example.com/", resolver=public, transport=ok_transport()
        )


def test_nonstandard_port_rejected():
    with pytest.raises(UnsafeUrlError):
        fetch_url(
            "https://example.com:8443/", resolver=public, transport=ok_transport()
        )


def test_explicit_443_allowed():
    page = fetch_url(
        "https://example.com:443/", resolver=public, transport=ok_transport()
    )
    assert page.content_type == "text/html"


def test_unresolvable_host():
    with pytest.raises(FetchError, match="resolve"):
        fetch_url(
            "https://nowhere.test/", resolver=lambda h: [], transport=ok_transport()
        )


def test_resolver_exception_becomes_fetch_error():
    def bad(host: str) -> list[str]:
        raise OSError("nope")

    with pytest.raises(FetchError, match="resolve"):
        fetch_url("https://nowhere.test/", resolver=bad, transport=ok_transport())


def test_redirect_to_private_blocked():
    t = redirect_transport("https://inner.test/")
    resolver = lambda h: [PUBLIC_IP] if h == "start.test" else ["10.1.1.1"]
    with pytest.raises(UnsafeUrlError):
        fetch_url("https://start.test/", resolver=resolver, transport=t)


def test_redirect_to_http_blocked():
    with pytest.raises(UnsafeUrlError, match="https"):
        fetch_url(
            "https://start.test/",
            resolver=public,
            transport=redirect_transport("http://plain.test/"),
        )


def test_redirect_followed_relative_and_final_url():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/a":
            return httpx.Response(301, headers={"location": "/b"})
        return html_response("done")

    page = fetch_url(
        "https://ok.test/a", resolver=public, transport=httpx.MockTransport(handler)
    )
    assert page.final_url == "https://ok.test/b"
    assert page.text == "done"


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_all_redirect_codes_followed(code):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(code, headers={"location": "/next"})
        return html_response("ok")

    page = fetch_url(
        "https://ok.test/", resolver=public, transport=httpx.MockTransport(handler)
    )
    assert page.text == "ok"


def test_redirect_missing_location():
    t = httpx.MockTransport(lambda request: httpx.Response(302))
    with pytest.raises(FetchError):
        fetch_url("https://ok.test/", resolver=public, transport=t)


def test_three_redirects_allowed_fourth_rejected():
    def make(n_hops: int) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            hop = int(request.url.path.strip("/") or 0)
            if hop < n_hops:
                return httpx.Response(302, headers={"location": f"/{hop + 1}"})
            return html_response("end")

        return httpx.MockTransport(handler)

    assert (
        fetch_url("https://ok.test/", resolver=public, transport=make(3)).text == "end"
    )
    with pytest.raises(FetchError, match="redirects"):
        fetch_url("https://ok.test/", resolver=public, transport=make(4))


def test_too_many_redirects():
    with pytest.raises(FetchError, match="redirects"):
        fetch_url("https://loop.test/", resolver=public, transport=loop_transport())


def test_body_cap():
    with pytest.raises(FetchError, match="too large"):
        fetch_url(
            "https://big.test/", resolver=public, transport=big_transport(3_000_000)
        )


def test_body_cap_via_content_length():
    with pytest.raises(FetchError, match="too large"):
        fetch_url(
            "https://big.test/",
            resolver=public,
            transport=big_transport(3_000_000, declare=True),
        )


def test_body_exactly_at_cap_ok():
    page = fetch_url(
        "https://big.test/", resolver=public, transport=big_transport(MAX_BODY_BYTES)
    )
    assert len(page.text) == MAX_BODY_BYTES


def test_content_type_allowlist():
    with pytest.raises(FetchError, match="content type"):
        fetch_url(
            "https://img.test/", resolver=public, transport=ctype_transport("image/png")
        )


def test_missing_content_type_rejected():
    t = httpx.MockTransport(lambda request: httpx.Response(200, content=b"x"))
    with pytest.raises(FetchError, match="content type"):
        fetch_url("https://img.test/", resolver=public, transport=t)


def test_content_type_case_insensitive_with_params():
    page = fetch_url(
        "https://ok.test/",
        resolver=public,
        transport=ctype_transport("Text/HTML; Charset=UTF-8"),
    )
    assert page.content_type == "text/html"


def test_non_2xx_rejected():
    t = httpx.MockTransport(lambda request: httpx.Response(404))
    with pytest.raises(FetchError, match="HTTP 404"):
        fetch_url("https://ok.test/", resolver=public, transport=t)


def test_timeout_becomes_fetch_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(FetchError, match="Could not fetch"):
        fetch_url(
            "https://ok.test/", resolver=public, transport=httpx.MockTransport(handler)
        )


def test_transport_error_becomes_fetch_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(FetchError, match="Could not fetch"):
        fetch_url(
            "https://ok.test/", resolver=public, transport=httpx.MockTransport(handler)
        )


def test_sends_generic_user_agent():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["ua"] = request.headers["user-agent"]
        return html_response()

    fetch_url(
        "https://ok.test/", resolver=public, transport=httpx.MockTransport(handler)
    )
    assert seen["ua"] == "PhoebeDemoFetcher/1.0"


def test_decodes_declared_charset():
    t = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/plain; charset=latin-1"},
            content="caf\xe9".encode("latin-1"),
        )
    )
    assert fetch_url("https://ok.test/", resolver=public, transport=t).text == "caf\xe9"


def test_invalid_utf8_replaced():
    t = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-type": "text/plain"}, content=b"ok\xff\xfe"
        )
    )
    assert fetch_url("https://ok.test/", resolver=public, transport=t).text == "ok��"


def test_unknown_charset_falls_back():
    t = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/plain; charset=bogus-enc"},
            content=b"abc",
        )
    )
    assert fetch_url("https://ok.test/", resolver=public, transport=t).text == "abc"


def test_google_doc_export_url():
    assert (
        google_doc_export_url(
            "https://docs.google.com/document/d/abc123/edit?usp=sharing"
        )
        == "https://docs.google.com/document/d/abc123/export?format=txt"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/document/d/abc/edit",
        "https://docs.google.com/spreadsheets/d/abc/edit",
        "http://docs.google.com/document/d/abc/edit",
        "https://docs.google.com.evil.test/document/d/abc/edit",
        "not a url",
    ],
)
def test_google_doc_export_url_none(url):
    assert google_doc_export_url(url) is None


def test_resolver_receives_punycode_host():
    seen: list[str] = []

    def resolver(host: str) -> list[str]:
        seen.append(host)
        return [PUBLIC_IP]

    fetch_url("https://faß.de/", resolver=resolver, transport=ok_transport())
    assert seen == ["xn--fa-hia.de"]


def test_overall_deadline_across_slow_body():
    now = [0.0]

    def slow_body():
        for _ in range(5):
            now[0] += 6.0
            yield b"x"

    t = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-type": "text/plain"}, content=slow_body()
        )
    )
    with pytest.raises(FetchError, match="too long"):
        fetch_url(
            "https://slow.test/", resolver=public, transport=t, clock=lambda: now[0]
        )


def test_overall_deadline_across_redirects():
    now = [0.0]

    def handler(request: httpx.Request) -> httpx.Response:
        now[0] += 6.0
        return httpx.Response(302, headers={"location": "/again"})

    with pytest.raises(FetchError, match="too long"):
        fetch_url(
            "https://slow.test/",
            resolver=public,
            transport=httpx.MockTransport(handler),
            clock=lambda: now[0],
        )


def test_gzip_response_rejected():
    import gzip

    t = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/plain", "content-encoding": "gzip"},
            content=gzip.compress(b"hello"),
        )
    )
    with pytest.raises(FetchError, match="Compressed"):
        fetch_url("https://ok.test/", resolver=public, transport=t)


def test_requests_identity_encoding():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["ae"] = request.headers["accept-encoding"]
        return html_response()

    fetch_url(
        "https://ok.test/", resolver=public, transport=httpx.MockTransport(handler)
    )
    assert seen["ae"] == "identity"


def test_decoding_error_becomes_fetch_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.DecodingError("bad", request=request)

    with pytest.raises(FetchError, match="Could not fetch"):
        fetch_url(
            "https://ok.test/", resolver=public, transport=httpx.MockTransport(handler)
        )


def test_stream_error_becomes_fetch_error():
    def body():
        yield b"x"
        raise httpx.StreamConsumed()

    t = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-type": "text/plain"}, content=body()
        )
    )
    with pytest.raises(FetchError, match="Could not fetch"):
        fetch_url("https://ok.test/", resolver=public, transport=t)


def test_non_ascii_digit_content_length_ignored():
    t = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers=[(b"content-type", b"text/plain"), (b"content-length", b"\xb2")],
            content=b"abc",
        )
    )
    assert fetch_url("https://ok.test/", resolver=public, transport=t).text == "abc"
