# Vespa Client - Zero-Barrier Vast.ai Access

Simple client proxy for Vast.ai serverless endpoints. Eliminates all routing complexity.

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

Once started, point your application at the proxy:

### HTTP Requests

```python
import requests

# Your code stays exactly the same - just change the URL!
response = requests.post(
    "http://localhost:8010/v1/chat/completions",  # <- localhost instead of API
    json={
        "model": "llama-2-7b",
        "messages": [{"role": "user", "content": "Hello!"}],
        "max_tokens": 100,
    }
)

print(response.json())
```

### OpenAI SDK

```python
from openai import OpenAI

# Point at proxy
client = OpenAI(
    base_url="http://localhost:8010/v1",
    api_key="not-used"  # Proxy handles auth
)

response = client.chat.completions.create(
    model="llama-2-7b",
    messages=[{"role": "user", "content": "Hello!"}]
)

print(response.choices[0].message.content)
```

### Streaming

```python
import requests

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

Import directly for more control:

```python
from client import VastClient

# Initialize with account key (auto-fetches endpoint key)
from utils.endpoint_util import Endpoint
endpoint_key = Endpoint.get_endpoint_api_key(
    endpoint_name="my-endpoint",
    account_api_key="YOUR_ACCOUNT_KEY",
    instance="prod"
)

# Or initialize with endpoint key directly
client = VastClient(
    endpoint_name="my-endpoint",
    api_key=endpoint_key,
)

# Make requests
response = client.post(
    "/v1/completions",
    json={
        "prompt": "Hello",
        "max_tokens": 50,
    }
)

print(response.json())
```

### All HTTP Methods

```python
client.get("/health")
client.post("/v1/completions", json={...})
client.put("/update", json={...})
client.patch("/modify", json={...})
client.delete("/remove")
```

### Custom Workload

```python
# Auto-detected from max_tokens, max_new_tokens, steps
client.post("/v1/completions", json={"max_tokens": 500})

# Or specify manually
client.post("/endpoint", json={...}, workload=500.0)
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

---

## Examples

### Quick Test

```bash
# Start proxy
python client.py

# In another terminal
curl http://localhost:8010/v1/completions \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello", "max_tokens": 50}'
```

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

# Use normally
```

```python
import requests

response = requests.post(
    "http://localhost:8010/v1/completions",
    json={"prompt": "test", "max_tokens": 100}
)
```

**Total:** 1 command + 5 lines of normal code

---

## Advanced

### Custom Routing

```python
from client import VastClient

client = VastClient(endpoint_name="my-endpoint", api_key="KEY")

# Get routing info manually
routing = client.route(endpoint="/v1/completions", workload=500.0)
print(routing)
# {'url': 'https://worker-ip:3000', 'signature': '...', ...}
```

### Custom Headers

```python
response = client.post(
    "/endpoint",
    json={...},
    headers={"X-Custom": "value"},
)
```

### Timeouts

```python
# Default timeout is 300 seconds
response = client.post("/endpoint", json={...}, timeout=60)
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

---

## Resources

- **Vast.ai Console:** https://console.vast.ai
- **Account API Key:** https://console.vast.ai/account
- **Endpoints:** https://console.vast.ai/endpoints
- **Discord:** https://discord.gg/Pa9M29FFye
- **Subreddit:** https://reddit.com/r/vastai/

## License

MIT License - see LICENSE file for details.
