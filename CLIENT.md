# Vespa Client - Zero-Barrier Vast.ai Access

Simple client proxy for Vast.ai serverless endpoints. Starts a local HTTP proxy that handles all routing complexity.

## Quick Start (3 Ways)

### 1. Interactive Mode (Easiest!)

Just run the client:

```bash
python client.py
```

It will:
1. Prompt for your account API key
2. Show all your endpoints
3. Let you select one
4. Auto-fetch the endpoint key
5. Start the proxy

**That's it!** Point your app at `localhost:8010`.

### 2. Account Key (One Command)

```bash
python client.py --endpoint my-endpoint --account-key YOUR_ACCOUNT_KEY
```

Auto-fetches the endpoint key for you.

### 3. Endpoint Key (If You Have It)

```bash
python client.py --endpoint my-endpoint --api-key ENDPOINT_KEY
```

Traditional approach if you already have the endpoint API key.

---

## Key Features

### ✅ Native Streaming Support

The proxy automatically detects and streams responses:
- Server-Sent Events (SSE)
- NDJSON streams
- Chunked transfer encoding
- Any response with "stream" in Content-Type

No buffering - tokens flow through as they're generated.

### ✅ No API Key Confusion

The client handles both key types:
- **Account API key** - Your main Vast.ai key (auto-fetches endpoint key)
- **Endpoint API key** - Per-endpoint key (if you have it)

Most users should use account key with `--account-key` or interactive mode.

### ✅ Endpoint Discovery

```bash
# List all your endpoints
python client.py --list --account-key YOUR_KEY
```

### ✅ Multiple Ways to Provide Keys

Priority order (first found wins):

1. **CLI flags** - `--account-key` or `--api-key`
2. **Environment variables** - `VAST_ACCOUNT_KEY`, `VAST_ENDPOINT`, `VAST_API_KEY`
3. **File** - `~/.vast_api_key` (vastai CLI compatible)

### ✅ Helpful Error Messages

Get clear guidance when something goes wrong:
```
ERROR: 401 Unauthorized

HINT: 401 Unauthorized usually means:
  - You're using the wrong API key type
  - Endpoint API key is required, not account API key
  - Use --account-key to auto-fetch the correct key
```

---

## All Usage Methods

### Interactive Mode

```bash
# No arguments = interactive prompts
python client.py
```

**Output:**
```
============================================================
  Vespa Client - Interactive Setup
============================================================

First, we need your Vast.ai account API key.
(Get it from: https://console.vast.ai/account)

Enter account API key: ****

Fetching your endpoints...

Available endpoints (3):
  1. my-llm-endpoint
  2. my-comfyui-endpoint
  3. test-endpoint

Select endpoint [1-3]: 1

Local proxy port [8010]:

Fetching endpoint API key for 'my-llm-endpoint'...
Successfully retrieved endpoint API key

============================================================
  Starting proxy for: my-llm-endpoint
  Listening on: http://127.0.0.1:8010
============================================================
```

### Command Line with Account Key

```bash
# Basic
python client.py --endpoint my-endpoint --account-key YOUR_ACCOUNT_KEY

# Custom port
python client.py --endpoint my-endpoint --account-key YOUR_KEY --port 8080

# Debug mode
python client.py --endpoint my-endpoint --account-key YOUR_KEY --debug
```

### Environment Variables

```bash
# Set once
export VAST_ACCOUNT_KEY="your-account-key"
export VAST_ENDPOINT="my-endpoint"

# Just run
python client.py
```

### File-Based (vastai CLI compatible)

```bash
# Create key file
echo "your-account-key" > ~/.vast_api_key

# Run with endpoint name
python client.py --endpoint my-endpoint
```

### List Endpoints

```bash
# With flag
python client.py --list --account-key YOUR_KEY

# With env var
export VAST_ACCOUNT_KEY="your-key"
python client.py --list

# With file
echo "your-key" > ~/.vast_api_key
python client.py --list
```

**Output:**
```
Available endpoints (3):
  • my-llm-endpoint
  • my-comfyui-endpoint
  • test-endpoint
```

---

## Using the Proxy

Once started, the proxy runs locally and forwards all requests to Vast.ai.

### With OpenAI SDK

```python
from openai import OpenAI

# Point at the proxy - it handles all Vast.ai routing!
client = OpenAI(
    base_url="http://localhost:8010/v1",
    api_key="not-used"  # Proxy handles authentication
)

# Use normally - streaming works automatically
response = client.chat.completions.create(
    model="llama-2-7b",
    messages=[{"role": "user", "content": "Hello!"}],
    stream=True,  # Native streaming support!
)

for chunk in response:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

### With Requests

```python
import requests

# Regular request (default workload=1.0)
response = requests.post(
    "http://localhost:8010/v1/chat/completions",
    json={
        "model": "llama-2-7b",
        "messages": [{"role": "user", "content": "Hello!"}],
        "max_tokens": 100,
    }
)

print(response.json())
```

### Specifying Workload Cost

You can specify the workload cost using the `X-Serverless-Cost` header:

```python
import requests

# Specify cost explicitly via header
response = requests.post(
    "http://localhost:8010/v1/completions",
    headers={"X-Serverless-Cost": "500"},  # Indicate 500 workload units
    json={
        "prompt": "Write a long story",
        "max_tokens": 1000,
    }
)
```

**Why specify cost?**
- Helps the autoscaler route requests to workers with appropriate capacity
- Used for queue time estimation and scaling decisions
- Default is 1.0 if not specified

### Streaming Responses

```python
import requests

# Streaming is detected automatically!
response = requests.post(
    "http://localhost:8010/v1/completions",
    json={"prompt": "test", "stream": True},
    stream=True,
)

for chunk in response.iter_content(chunk_size=None):
    print(chunk.decode(), end="")
```

---

## Python Module Usage

Use the client as a module for more control:

```python
from client import VastClient
import asyncio

async def main():
    # Initialize client
    client = VastClient(
        endpoint_name="my-endpoint",
        api_key="YOUR_ENDPOINT_KEY",
        port=8010,  # Optional, defaults to 8010
        host="127.0.0.1",  # Optional
    )

    # Start the proxy
    await client.start()

    # Now use client.url with any SDK!
    print(f"Proxy running at: {client.url}")

    # Example with OpenAI SDK
    from openai import OpenAI
    openai_client = OpenAI(
        base_url=f"{client.url}/v1",
        api_key="not-used"
    )

    response = openai_client.chat.completions.create(
        model="llama-2-7b",
        messages=[{"role": "user", "content": "Hello!"}]
    )

    print(response.choices[0].message.content)

    # Keep running (or await client.stop() to shut down)
    await asyncio.sleep(3600)
    await client.stop()

# Run it
asyncio.run(main())
```

### Auto-Fetching Endpoint Key

```python
from client import VastClient, fetch_endpoint_key
import asyncio

async def main():
    # Fetch endpoint key using account key
    account_key = "YOUR_ACCOUNT_KEY"
    endpoint_key = fetch_endpoint_key(
        account_key=account_key,
        endpoint_name="my-endpoint",
        instance="prod"  # or "alpha", "candidate"
    )

    # Start client
    client = VastClient(
        endpoint_name="my-endpoint",
        api_key=endpoint_key,
    )

    await client.start()
    print(f"Proxy URL: {client.url}")

    # Use with any HTTP client
    import requests
    response = requests.get(f"{client.url}/v1/models")
    print(response.json())

    await client.stop()

asyncio.run(main())
```

### Running Forever

```python
from client import VastClient
import asyncio

async def main():
    client = VastClient(
        endpoint_name="my-endpoint",
        api_key="YOUR_KEY",
    )

    # Start and run until interrupted
    await client.run_forever()

asyncio.run(main())
```

---

## Configuration Reference

### CLI Arguments

```bash
python client.py --help

Arguments:
  --endpoint ENDPOINT       Vast.ai endpoint name (or set VAST_ENDPOINT)
  --api-key KEY            Endpoint API key (or set VAST_API_KEY)
  --account-key KEY        Account API key - auto-fetches endpoint key
                           (or set VAST_ACCOUNT_KEY, or use ~/.vast_api_key)
  --list                   List available endpoints (requires account key)
  --port PORT              Local proxy port (default: 8010)
  --host HOST              Local proxy host (default: 127.0.0.1)
  --autoscaler-url URL     Autoscaler URL (default: https://run.vast.ai)
  --instance INSTANCE      Vast.ai instance: prod, alpha, candidate (default: prod)
  --debug                  Enable debug logging
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `VAST_ACCOUNT_KEY` | Account API key (for auto-fetching) |
| `VAST_ENDPOINT` | Endpoint name |
| `VAST_API_KEY` | Endpoint API key (if you have it) |

### File

Create `~/.vast_api_key` with your account API key (compatible with vastai CLI).

### Priority Order

When multiple sources are provided:
1. CLI flags (highest priority)
2. Environment variables
3. `~/.vast_api_key` file (lowest priority)

---

## Getting Your API Key

### Account API Key (Recommended)

1. Go to https://console.vast.ai/account
2. Copy your API key
3. Use with `--account-key` flag

**Use this for:** Auto-fetching endpoint keys, listing endpoints, interactive mode

### Endpoint API Key (Advanced)

1. Go to https://console.vast.ai/endpoints
2. Find your endpoint
3. Copy the endpoint-specific API key

**Use this for:** Direct access when you already have the endpoint key

---

## Troubleshooting

### No ~/.vast_api_key File

```bash
# Create it
echo "your-account-key" > ~/.vast_api_key
chmod 600 ~/.vast_api_key  # Secure it
```

### 401 Unauthorized

**Problem:** Wrong API key type

**Solution:** Use account key with `--account-key` or interactive mode:
```bash
python client.py --endpoint my-endpoint --account-key YOUR_ACCOUNT_KEY
```

### No Endpoints Found

**Problem:** `--list` shows no endpoints

**Solutions:**
- Verify you have created endpoints at console.vast.ai
- Check you're using the correct account API key
- Try `--instance alpha` if using alpha environment

### Connection Refused

**Problem:** `Connection refused to localhost:8010`

**Solution:** Make sure the proxy is running:
```bash
python client.py --endpoint my-endpoint --account-key YOUR_KEY
```

### Endpoint Not Found

**Problem:** `Endpoint 'xyz' not found`

**Solutions:**
- List your endpoints: `python client.py --list --account-key KEY`
- Verify endpoint name is correct
- Check endpoint exists in console.vast.ai

### Streaming Not Working

**Problem:** Responses are buffered instead of streaming

**Solution:** The proxy auto-detects streaming. Make sure:
- Your backend sends appropriate headers (Content-Type: text/event-stream)
- Your client uses `stream=True` (requests) or equivalent
- You're iterating over chunks, not reading the full response

---

## Examples

### Quick Test

```bash
# Start proxy
python client.py

# In another terminal - Test GET request
curl http://localhost:8010/v1/models

# Test POST request (default workload=1.0)
curl http://localhost:8010/v1/completions \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello", "max_tokens": 50}'

# Test POST request with explicit workload cost
curl http://localhost:8010/v1/completions \
  -H "Content-Type: application/json" \
  -H "X-Serverless-Cost: 500" \
  -d '{"prompt": "Long story", "max_tokens": 2000}'

# Test streaming
curl http://localhost:8010/v1/completions \
  -H "Content-Type: application/json" \
  -d '{"prompt": "test", "stream": true}' \
  --no-buffer
```

**Note:**
- The proxy automatically handles GET/DELETE/HEAD requests by encoding auth_data as query parameters
- Use `X-Serverless-Cost` header to specify workload units (defaults to 1.0 if not specified)
- Workload cost is used for routing and queue estimation
- Streaming is detected automatically based on response headers

### Production Setup

```bash
# Create config
echo "your-account-key" > ~/.vast_api_key
export VAST_ENDPOINT="production-endpoint"

# Run proxy
python client.py

# Deploy your app pointing at localhost:8010
```

### Multiple Endpoints

```bash
# Endpoint 1 on port 8010
python client.py --endpoint endpoint1 --account-key KEY --port 8010 &

# Endpoint 2 on port 8011
python client.py --endpoint endpoint2 --account-key KEY --port 8011 &

# App can use both
curl http://localhost:8010/v1/completions -d '{...}'
curl http://localhost:8011/v1/completions -d '{...}'
```

### With Different SDKs

```python
# OpenAI SDK
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8010/v1", api_key="x")

# Anthropic SDK (if your backend is compatible)
from anthropic import Anthropic
client = Anthropic(base_url="http://localhost:8010", api_key="x")

# LangChain
from langchain.llms import OpenAI
llm = OpenAI(openai_api_base="http://localhost:8010/v1", openai_api_key="x")

# Plain requests
import requests
requests.post("http://localhost:8010/v1/chat/completions", json={...})
```

---

## Comparison

### Before (Manual Routing)

```python
import requests

# Step 1: Get worker assignment
route_response = requests.post(
    "https://run.vast.ai/route/",
    headers={"Authorization": f"Bearer {endpoint_api_key}"},
    json={"endpoint": "/v1/completions", "cost": 100},
)
routing = route_response.json()

# Step 2: Wrap request
payload = {
    "auth_data": {
        "cost": routing["cost"],
        "endpoint": "/v1/completions",
        "reqnum": routing["reqnum"],
        "request_idx": routing["request_idx"],
        "signature": routing["signature"],
        "url": routing["url"],
    },
    "payload": {
        "prompt": "test",
        "max_tokens": 100,
    }
}

# Step 3: Send to worker
response = requests.post(routing["url"], json=payload)
```

**Total:** ~30 lines of complex boilerplate

### After (With Vespa Client)

```bash
# Start proxy once
python client.py
```

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8010/v1", api_key="x")
response = client.chat.completions.create(
    model="llama-2-7b",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

**Total:** 1 command + 5 lines of normal SDK code

---

## Advanced Features

### Async Context Manager Pattern

```python
from client import VastClient
import asyncio

async def main():
    client = VastClient(endpoint_name="my-endpoint", api_key="KEY")

    try:
        await client.start()

        # Your code here
        print(f"Use: {client.url}")
        await asyncio.sleep(3600)

    finally:
        await client.stop()

asyncio.run(main())
```

### Custom Headers Pass-Through

The proxy forwards all headers to workers:

```python
import requests

response = requests.post(
    "http://localhost:8010/v1/completions",
    headers={
        "X-Serverless-Cost": "500",  # Used by proxy for routing
        "X-Custom-Header": "value",   # Passed through to worker
    },
    json={...}
)
```

### Workload Estimation

```python
# For token-based workload:
# Estimate tokens, set as cost
estimated_tokens = len(prompt.split()) * 1.5 + max_tokens
headers = {"X-Serverless-Cost": str(estimated_tokens)}

# For request-based workload:
# Each request = 1.0 workload
headers = {"X-Serverless-Cost": "1.0"}

response = requests.post(
    "http://localhost:8010/endpoint",
    headers=headers,
    json={...}
)
```

---

## Why Use the Client?

- **Zero Barrier** - Interactive mode requires zero knowledge
- **No Confusion** - Handles both API key types automatically
- **Discovery** - Built-in endpoint listing
- **Compatible** - Works with vastai CLI (`~/.vast_api_key`)
- **Flexible** - CLI, environment, file, or interactive
- **Helpful** - Clear error messages guide you
- **Standard** - Use any HTTP client/SDK normally
- **Streaming** - Native support for SSE, NDJSON, chunked responses
- **Simple** - Just `client.url` - works with any SDK

---

## Architecture

```
Your App (OpenAI SDK, requests, etc.)
    ↓
Local Proxy (localhost:8010)
    ↓ (calls /route/)
Vast.ai Autoscaler (routing + auth)
    ↓ (returns worker URL + signature)
Local Proxy (wraps in auth_data)
    ↓ (forwards with auth)
Vespa Worker (validates signature)
    ↓ (proxies to backend)
Your Model Backend (vLLM, TGI, etc.)
    ↓ (streams response)
Vespa Worker (streams back)
    ↓
Local Proxy (streams to you)
    ↓
Your App (receives tokens as generated)
```

**Key benefits:**
- All complexity hidden behind localhost proxy
- Streaming works transparently
- Use any SDK without modifications
- Single source of truth for routing logic

---

## Resources

- **Vast.ai Console:** https://console.vast.ai
- **Account API Key:** https://console.vast.ai/account
- **Endpoints:** https://console.vast.ai/endpoints
- **Discord:** https://discord.gg/Pa9M29FFye
- **Subreddit:** https://reddit.com/r/vastai/

## License

MIT License - see LICENSE file for details.
