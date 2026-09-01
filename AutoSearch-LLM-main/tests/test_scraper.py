"""Page-fetch guardrails: size cap, content type, extraction robustness."""

from __future__ import annotations

import httpx
import pytest

from backend.services.errors import ContentTooLargeError, UnsupportedContentTypeError
from backend.services.scraper import extract_main_text, fetch_html


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fetches_html_successfully():
    def handler(request):
        return httpx.Response(
            200, headers={"content-type": "text/html; charset=utf-8"},
            content=b"<html><body><p>hello world</p></body></html>",
        )

    async with _client(handler) as client:
        html = await fetch_html("https://x.example.com", client=client)
    assert "hello world" in html


async def test_non_html_content_type_is_rejected():
    """A PDF must not be fed to the HTML parser as if it were a page."""
    def handler(request):
        return httpx.Response(
            200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.4 ..."
        )

    async with _client(handler) as client:
        with pytest.raises(UnsupportedContentTypeError):
            await fetch_html("https://x.example.com/doc.pdf", client=client)


async def test_missing_content_type_is_tolerated():
    def handler(request):
        return httpx.Response(200, content=b"<html><body>ok</body></html>")

    async with _client(handler) as client:
        assert "ok" in await fetch_html("https://x.example.com", client=client)


async def test_declared_oversize_body_is_rejected_without_downloading():
    def handler(request):
        return httpx.Response(
            200,
            headers={"content-type": "text/html", "content-length": "99999999"},
            content=b"<html></html>",
        )

    async with _client(handler) as client:
        with pytest.raises(ContentTooLargeError):
            await fetch_html("https://x.example.com", client=client, max_bytes=1000)


async def test_streamed_body_is_capped_mid_download():
    """The cap must abort during streaming, not after buffering everything."""
    big = b"<html><body>" + (b"x" * 50_000) + b"</body></html>"

    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/html"}, content=big)

    async with _client(handler) as client:
        with pytest.raises(ContentTooLargeError):
            await fetch_html("https://x.example.com", client=client, max_bytes=1000)


async def test_http_error_status_raises():
    def handler(request):
        return httpx.Response(404, headers={"content-type": "text/html"}, content=b"nope")

    async with _client(handler) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await fetch_html("https://x.example.com", client=client)


# ------------------------------------------------------------- extraction
@pytest.mark.parametrize(
    "payload",
    [
        "",
        "   ",
        "<html>",
        "<html><body></body></html>",
        "not markup at all",
        "\x00\x01\x02 binary",
        "<html><body><p>" + ("word " * 200) + "</p></body></html>",
    ],
)
def test_extraction_never_raises(payload):
    """Extraction is total: messy real-world input yields text or '', never an error."""
    result = extract_main_text(payload)
    assert isinstance(result, str)


def test_extraction_pulls_article_text():
    html = "<html><body><article><p>" + ("meaningful sentence. " * 40) + "</p></article></body></html>"
    assert "meaningful sentence" in extract_main_text(html)
