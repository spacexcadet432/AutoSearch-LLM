import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def generate_standard_answer(query: str):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": query}
        ],
        temperature=0.3
    )

    return {
        "answer": response.choices[0].message.content,
        "sources": None
    }


def generate_grounded_answer(query: str, search_results: list):
    formatted_sources = ""

    for i, result in enumerate(search_results):
        formatted_sources += f"""
Source {i+1}:
Title: {result['title']}
Content: {result['content']}
URL: {result['url']}
"""

    prompt = f"""
You are an AI assistant that MUST answer using ONLY the provided sources below.

If the answer is not clearly supported by the sources, say:
"Insufficient verified information."

Cite sources inline using (Source 1), (Source 2), etc.

User Question:
{query}

Available Sources:
{formatted_sources}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You strictly follow source grounding rules."},
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )

    return {
        "answer": response.choices[0].message.content,
        "sources": [r["url"] for r in search_results]
    }

if __name__ == "__main__":
    from search import web_search

    query = "Stranger Things season 5 release date"
    results = web_search(query)

    answer = generate_grounded_answer(query, results)

    print("\nANSWER:\n")
    print(answer["answer"])
    print("\nSOURCES:\n")
    print(answer["sources"])