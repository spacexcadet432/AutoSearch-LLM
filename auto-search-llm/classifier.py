import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def is_time_sensitive(query: str) -> bool:
    prompt = f"""
You are a classifier.

Determine whether the following question requires current or post-2023 real-time information to answer accurately.

Respond with ONLY one word:
YES
or
NO

Question: "{query}"
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a precise classifier."},
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )

    answer = response.choices[0].message.content.strip().upper()

    return answer == "YES"


if __name__ == "__main__":
    print(is_time_sensitive("Stranger Things season 5 release date?"))
    print(is_time_sensitive("Explain overfitting in ML"))