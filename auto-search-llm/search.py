import os
from openai import OpenAI
import requests
from dotenv import load_dotenv

load_dotenv()

TAVILY_API_KEY=os.getenv("TAVILY_API_KEY")
def web_search(query: str):
    url = "https://api.tavily.com/search"

    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "basic",
        "max_results": 3
    }

    response = requests.post(url, json=payload)

    if response.status_code != 200:
        raise Exception(f"Search API Error: {response.text}")

    data = response.json()

    results = []

    for item in data.get("results", []):
        results.append({
            "title": item.get("title"),
            "content": item.get("content"),
            "url": item.get("url")
        })

    return results


if __name__ == "__main__":
    results = web_search("Stranger Things season 5 release date")
    for r in results:
        print("\n---")
        print("Title:", r["title"])
        print("URL:", r["url"])
        print("Content:", r["content"])