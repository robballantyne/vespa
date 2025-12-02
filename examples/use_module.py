"""
Example: Using VastClient as a Python module

Import the client directly into your code for more control.
"""
import sys
sys.path.insert(0, "..")  # Add parent directory to path

from client import VastClient

# Initialize client with your endpoint
client = VastClient(
    endpoint_name="my-endpoint",
    api_key="YOUR_ENDPOINT_API_KEY",  # Or set VAST_API_KEY env var
)

# Example 1: Simple completion
response = client.post(
    "/v1/completions",
    json={
        "model": "llama-2-7b",
        "prompt": "Once upon a time",
        "max_tokens": 50,
    }
)

print("Completion:", response.json())

# Example 2: Chat completion
response = client.post(
    "/v1/chat/completions",
    json={
        "model": "llama-2-7b",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is the capital of France?"}
        ],
        "max_tokens": 50,
    }
)

print("Chat:", response.json())

# Example 3: Streaming
response = client.post(
    "/v1/completions",
    json={
        "model": "llama-2-7b",
        "prompt": "Write a haiku about programming:",
        "max_tokens": 50,
        "stream": True,
    },
    stream=True,
)

print("Streaming:")
for chunk in response.iter_content(chunk_size=None):
    if chunk:
        print(chunk.decode(), end="", flush=True)
print()

# Example 4: GET request
response = client.get("/health")
print("Health:", response.text)

# The client handles all Vast.ai routing automatically:
# - Calls /route/ to get worker assignment
# - Wraps request in auth_data + payload
# - Auto-detects workload from max_tokens, max_new_tokens, or steps
# - Returns standard requests.Response object
