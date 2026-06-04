from dotenv import dotenv_values
import anthropic
from pathlib import Path

# Load key directly from .env (bypasses os.environ propagation quirks)
env = dotenv_values(Path(__file__).parent / ".env")
api_key = env.get("ANTHROPIC_API_KEY")

if not api_key:
    raise ValueError(".env file found but ANTHROPIC_API_KEY is missing or empty.")

client = anthropic.Anthropic(api_key=api_key)

message = client.messages.create(
    model="claude-opus-4-5",
    max_tokens=1024,
    messages=[
        {"role": "user", "content": "Hello, confirm this is working"}
    ]
)

print(message.content[0].text)
