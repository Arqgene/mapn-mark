from openai import OpenAI, RateLimitError
import os

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def call_llm(messages):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=50,
            temperature=0.4
        )
        print("✓ Primary model used: gpt-4o-mini")
        return response

    except RateLimitError:
        print("⚠ Primary model quota exceeded. Trying fallback...")

        try:
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                max_tokens=50,
                temperature=0.4
            )
            print("✓ Fallback model used: gpt-3.5-turbo")
            return response

        except RateLimitError:
            print("✗ All models blocked by quota.")
            return None


if __name__ == "__main__":
    messages = [
        {"role": "system", "content": "You are a test assistant."},
        {"role": "user", "content": "Say hello."}
    ]

    result = call_llm(messages)

    if result:
        print("\n--- Model Reply ---")
        print(result.choices[0].message.content)
    else:
        print("\nNo response due to insufficient quota.")
