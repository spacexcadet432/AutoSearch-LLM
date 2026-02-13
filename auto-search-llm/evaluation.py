import json
from generator import generate_standard_answer
from pipeline import answer_question


def load_test_queries():
    with open("test_queries.json", "r") as f:
        return json.load(f)


def evaluate():
    test_data = load_test_queries()

    total = len(test_data)
    correct_routing = 0

    print("\nStarting Evaluation...\n")

    for item in test_data:
        query = item["query"]
        expected_type = item["expected_type"]

        result = answer_question(query)

        predicted_mode = result["mode"]

        if expected_type == "time_sensitive" and predicted_mode == "grounded":
            correct_routing += 1
        elif expected_type == "timeless" and predicted_mode == "standard":
            correct_routing += 1

        print(f"Query: {query}")
        print(f"Expected: {expected_type}")
        print(f"Predicted Mode: {predicted_mode}")
        print("-" * 50)

    accuracy = correct_routing / total * 100

    print("\nEvaluation Complete")
    print(f"Routing Accuracy: {accuracy:.2f}%")
    print(f"Correct Decisions: {correct_routing}/{total}")


if __name__ == "__main__":
    evaluate()