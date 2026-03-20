import os
import asyncio
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

SERPER_API_KEY = os.getenv("SERPER_API_KEY")
SERPER_ENDPOINT = "https://google.serper.dev/search"


async def discover_urls(query: str, k: int = 8, *, country: str = "us", language: str = "en") -> list[dict]:
    """
    URL discovery only (no scraping).
    Returns a list of {title, url, snippet}.
    """
    if not SERPER_API_KEY:
        raise RuntimeError("Missing SERPER_API_KEY in environment.")

    payload: dict[str, Any] = {
        "q": query,
        "num": k,
        "gl": country,
        "hl": language,
    }

    headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json",
    }

    timeout = httpx.Timeout(10.0, connect=5.0)

    # Small retry loop for transient issues; keeps the portfolio code simple.
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
                resp = await client.post(SERPER_ENDPOINT, json=payload)
                if resp.status_code != 200:
                    raise RuntimeError(f"Serper API error {resp.status_code}: {resp.text[:500]}")

                data = resp.json()
                organic = data.get("organic", []) or []

                results: list[dict] = []
                seen = set()
                for item in organic:
                    url = item.get("link")
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    results.append(
                        {
                            "title": item.get("title"),
                            "url": url,
                            "snippet": item.get("snippet"),
                        }
                    )
                    if len(results) >= k:
                        break

                return results
        except Exception as e:  # noqa: BLE001 - portfolio-friendly error handling
            last_exc = e
            # backoff: 250ms -> 500ms
            await asyncio.sleep(0.25 * (attempt + 1))

    # If both attempts fail, surface the last exception.
    assert last_exc is not None
    raise last_exc


if __name__ == "__main__":
    async def _main():
        r = await discover_urls("Stranger Things season 5 release date", k=5)
        for x in r:
            print("---")
            print("Title:", x["title"])
            print("URL:", x["url"])
            print("Snippet:", (x.get("snippet") or "")[:120])

    asyncio.run(_main())