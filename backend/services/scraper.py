"""Async page fetching and extraction utilities."""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup
from readability import Document

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


def _clean_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_main_text(html: str) -> str:
    """Extract readable article text from raw HTML."""
    try:
        doc = Document(html)
        summary_html = doc.summary()
        soup = BeautifulSoup(summary_html, "lxml")
        text = _clean_text(soup.get_text(separator="\n"))
        if len(text) > 250:
            return text
    except Exception:
        pass

    soup = BeautifulSoup(html, "lxml")
    return _clean_text(soup.get_text(separator="\n"))


async def fetch_html(
    url: str,
    *,
    client: httpx.AsyncClient,
    timeout_s: float = 8.0,
    max_bytes: int = 1_500_000,
) -> str:
    """Fetch a URL with timeout and max-size guardrails."""
    response = await client.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout_s,
        follow_redirects=True,
    )
    response.raise_for_status()
    content = response.content
    if len(content) > max_bytes:
        raise RuntimeError(f"Page too large: {len(content)} bytes")
    return content.decode(response.encoding or "utf-8", errors="ignore")
