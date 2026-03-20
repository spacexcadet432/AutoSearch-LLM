from classifier import is_time_sensitive
from generator import generate_standard_answer, generate_grounded_answer
from retrieval import retrieve_sources


async def answer_question(query: str):
    print("\n[Pipeline] Checking if time-sensitive...")
    if await is_time_sensitive(query):
        print("[Pipeline] Time-sensitive detected. Running web search...")
        sources = await retrieve_sources(query)

        print("[Pipeline] Generating grounded answer...")
        response = await generate_grounded_answer(query, sources)

        return {
            "mode": "grounded",
            "answer": response["answer"],
            "sources": response["sources"]
        }

    else:
        print("[Pipeline] Not time-sensitive. Using standard LLM answer...")
        response = await generate_standard_answer(query)

        return {
            "mode": "standard",
            "answer": response["answer"],
            "sources": None
        }


if __name__ == "__main__":
    import asyncio

    user_query = input("Enter your question: ")
    result = asyncio.run(answer_question(user_query))

    print("\n--- FINAL OUTPUT ---")
    print("Mode:", result["mode"])
    print("\nAnswer:\n")
    print(result["answer"])

    if result["sources"]:
        print("\nSources:")
        for s in result["sources"]:
            print("-", s)