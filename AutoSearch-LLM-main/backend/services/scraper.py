"""Async page fetching and extraction utilities."""

from __future__ import annotations

import logging
import re
from html import unescape

import httpx
from bs4 import BeautifulSoup
from readability import Document

from backend.services.errors import ContentTooLargeError, UnsupportedContentTypeError

logger = logging.getLogger(__name__)

# readability logs a full traceback for every unparseable document. We already
# handle that case explicitly below, so its duplicate stack traces are pure
# noise that would bury genuine errors.
logging.getLogger("readability.readability").setLevel(logging.CRITICAL)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


def _clean_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def extract_main_text(html: str) -> str:
    """Extract readable article text from raw HTML.

    Total by design: extraction failure is an expected outcome for the messy
    real web (empty documents, malformed markup, parser crashes), so this
    returns "" instead of raising and the caller treats it as thin content.
    """
    if not html or not html.strip():
        return ""

    # Preferred: readability's main-article extraction.
    try:
        doc = Document(html)
        summary_html = doc.summary()
        soup = BeautifulSoup(summary_html, "lxml")
        text = _clean_text(soup.get_text(separator="\n"))
        if len(text) > 200:
            return text
    except Exception:
        logger.debug("extraction: readability failed, falling back", exc_info=True)

    # Fallback: strip scripts/styles and take the whole document text.
    try:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        fallback_text = _clean_text(soup.get_text(separator="\n"))
        if fallback_text:
            return fallback_text
    except Exception:
        logger.debug("extraction: soup fallback failed, using regex", exc_info=True)

    # Last resort for malformed HTML where parser extraction is poor.
    try:
        return _clean_text(re.sub(r"<[^>]+>", " ", html))
    except Exception:
        logger.debug("extraction: regex fallback failed", exc_info=True)
        return ""


# Content types we can meaningfully extract text from. Anything else (PDF,
# image, video, archive) would otherwise be fed to the HTML parser as garbage.
_TEXTUAL_CONTENT_TYPES = ("text/html", "application/xhtml", "text/plain", "application/xml", "text/xml")


async def fetch_html(
    url: str,
    *,
    client: httpx.AsyncClient,
    timeout_s: float = 8.0,
    max_bytes: int = 1_500_000,
) -> str:
    """Fetch a URL with timeout, content-type and streaming max-size guardrails.

    The body is streamed and aborted as soon as it exceeds ``max_bytes``. The
    previous implementation downloaded the entire response into memory and only
    then checked the size, so the cap provided no actual memory protection.
    """
    async with client.stream(
        "GET",
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout_s,
        follow_redirects=True,
    ) as response:
        response.raise_for_status()

        content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
        # An absent content-type is tolerated; an explicitly non-textual one is not.
        if content_type and not any(content_type.startswith(t) for t in _TEXTUAL_CONTENT_TYPES):
            raise UnsupportedContentTypeError(f"Unsupported content-type: {content_type}")

        # Trust a declared over-size body immediately instead of streaming it.
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > max_bytes:
            raise ContentTooLargeError(f"Page too large: {declared} bytes (declared)")

        buffer = bytearray()
        async for chunk in response.aiter_bytes():
            buffer.extend(chunk)
            if len(buffer) > max_bytes:
                # Abort the download rather than buffering the rest.
                raise ContentTooLargeError(f"Page too large: exceeded {max_bytes} bytes")

        return bytes(buffer).decode(response.encoding or "utf-8", errors="ignore")
