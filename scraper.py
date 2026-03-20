import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from readability import Document


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


def _clean_text(text: str) -> str:
    # Normalize whitespace and remove very repetitive blank lines.
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_main_text(html: str) -> str:
    """
    Convert HTML to "readable" main-text.
    Uses readability-lxml first, falls back to BeautifulSoup text extraction.
    """
    try:
        doc = Document(html)
        summary_html = doc.summary()
        soup = BeautifulSoup(summary_html, "lxml")
        text = soup.get_text(separator="\n")
        text = _clean_text(text)
        if len(text) > 300:
            return text
    except Exception:
        # Fall back below.
        pass

    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(separator="\n")
    text = _clean_text(text)
    return text


async def fetch_html(
    url: str,
    *,
    client: httpx.AsyncClient,
    timeout_s: float = 8.0,
    max_bytes: int = 1_500_000,
) -> str:
    """
    Fetch a URL and return HTML as text.
    Enforces a max download size to reduce memory blow-ups.
    """
    headers = {"User-Agent": USER_AGENT}

    resp = await client.get(url, headers=headers, timeout=timeout_s, follow_redirects=True)
    resp.raise_for_status()

    content = resp.content
    if len(content) > max_bytes:
        raise RuntimeError(f"Page too large: {len(content)} bytes")

    # Let httpx decode based on headers; fallback to utf-8.
    try:
        return content.decode(resp.encoding or "utf-8", errors="ignore")
    except Exception:
        return content.decode("utf-8", errors="ignore")


def estimate_page_metadata(url: str) -> dict[str, Optional[str]]:
    # Minimal metadata: title is already available from Serper,
    # but we keep a hook for later improvements (date extraction, domain, etc).
    return {"url": url}

