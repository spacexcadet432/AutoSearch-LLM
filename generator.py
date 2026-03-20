import os
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


async def generate_standard_answer(query: str):
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": query},
        ],
        temperature=0.3,
    )

    return {"answer": response.choices[0].message.content, "sources": None}


async def generate_grounded_answer(query: str, sources: list[dict]):
    formatted_sources = ""

    for i, s in enumerate(sources):
        chunk_text = (s.get("chunk_text") or "")[:1400]
        formatted_sources += f"""
Source {i+1}:
Title: {s.get('title') or 'N/A'}
URL: {s.get('url')}
Extracted Chunk (chunk_index={s.get('chunk_index')}) :
{chunk_text}
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

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You strictly follow source grounding rules."},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )

    return {
        "answer": response.choices[0].message.content,
        "sources": [s["url"] for s in sources],
    }

if __name__ == "__main__":
    import asyncio
    from retrieval import retrieve_sources

    async def _main():
        query = "Stranger Things season 5 release date"
        sources = await retrieve_sources(query, deadline_ms=2500)
        answer = await generate_grounded_answer(query, sources)

        print("\nANSWER:\n")
        print(answer["answer"])
        print("\nSOURCES:\n")
        print(answer["sources"])

    asyncio.run(_main())