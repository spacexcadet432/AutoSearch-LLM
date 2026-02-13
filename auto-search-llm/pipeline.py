from classifier import is_time_sensitive
from search import web_search
from generator import generate_standard_answer, generate_grounded_answer


def answer_question(query: str):
    print("\n[Pipeline] Checking if time-sensitive...")

    if is_time_sensitive(query):
        print("[Pipeline] Time-sensitive detected. Running web search...")
        results = web_search(query)

        print("[Pipeline] Generating grounded answer...")
        response = generate_grounded_answer(query, results)

        return {
            "mode": "grounded",
            "answer": response["answer"],
            "sources": response["sources"]
        }

    else:
        print("[Pipeline] Not time-sensitive. Using standard LLM answer...")
        response = generate_standard_answer(query)

        return {
            "mode": "standard",
            "answer": response["answer"],
            "sources": None
        }


if __name__ == "__main__":
    user_query = input("Enter your question: ")

    result = answer_question(user_query)

    print("\n--- FINAL OUTPUT ---")
    print("Mode:", result["mode"])
    print("\nAnswer:\n")
    print(result["answer"])

    if result["sources"]:
        print("\nSources:")
        for s in result["sources"]:
            print("-", s)