# Vespa Client

Simple client for Vast.ai serverless endpoints that abstracts away all the routing complexity.

## Problem

Using Vast.ai endpoints currently requires:
1. Call `run.vast.ai/route/` with endpoint API key
2. Get worker URL, signature, and routing info
3. Wrap your request in `auth_data` + `payload` format
4. Send to worker
5. Parse response

This is complex and error-prone!

## Solution

The Vespa client handles all of this automatically. Two ways to use it:

### Option 1: Local Proxy Server (Easiest!)

Start a local proxy that handles all Vast.ai routing:

```bash
# Start proxy
python client.py --endpoint my-endpoint --api-key YOUR_KEY

# Or use environment variable
export VAST_API_KEY="YOUR_KEY"
python client.py --endpoint my-endpoint
```

Now point your existing code at `localhost:8010` instead of the real API:

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

That's it! The proxy handles all the Vast.ai routing behind the scenes.

### Option 2: Python Module

Import the client directly for more control:

```python
from client import VastClient

# Initialize
client = VastClient(
    endpoint_name="my-endpoint",
    api_key="YOUR_KEY",
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

## Features

### Automatic Routing

The client automatically:
- ✅ Calls `/route/` to get worker assignment
- ✅ Wraps requests in `auth_data` + `payload` format
- ✅ Forwards to assigned worker
- ✅ Handles authentication and signatures
- ✅ Returns standard responses

### Workload Detection

Automatically detects workload from common fields:
- `max_tokens` (OpenAI)
- `max_new_tokens` (TGI)
- `steps` (ComfyUI)

Or specify manually:
```python
client.post("/endpoint", json={...}, workload=500.0)
```

### Streaming Support

```python
response = client.post(
    "/v1/completions",
    json={"prompt": "test", "stream": True},
    stream=True,
)

for chunk in response.iter_content(chunk_size=None):
    print(chunk.decode(), end="")
```

### All HTTP Methods

```python
client.get("/health")
client.post("/v1/completions", json={...})
client.put("/update", json={...})
client.patch("/modify", json={...})
client.delete("/remove")
```

## Installation

No installation needed! Just use the `client.py` file:

```bash
# Clone or download
git clone https://github.com/robballantyne/vespa
cd vespa

# Run proxy
python client.py --endpoint my-endpoint --api-key YOUR_KEY
```

Dependencies (already in requirements.txt):
- `requests`
- `aiohttp` (for proxy server only)

## Usage

### As Proxy Server

```bash
# Basic usage
python client.py --endpoint my-endpoint --api-key YOUR_KEY

# Custom port
python client.py --endpoint my-endpoint --api-key YOUR_KEY --port 8080

# Debug mode
python client.py --endpoint my-endpoint --api-key YOUR_KEY --debug

# Environment variable
export VAST_API_KEY="YOUR_KEY"
python client.py --endpoint my-endpoint
```

Then point your app at `http://localhost:8010` (or custom port).

### As Python Module

```python
from client import VastClient

# Initialize
client = VastClient(
    endpoint_name="my-endpoint",
    api_key="YOUR_KEY",
)

# Make requests
response = client.post("/v1/completions", json={
    "model": "my-model",
    "prompt": "test",
    "max_tokens": 50,
})

# Check response
if response.status_code == 200:
    print(response.json())
else:
    print(f"Error: {response.status_code}")
```

## Examples

See `examples/` directory:
- `use_proxy.py` - Using the proxy server
- `use_module.py` - Using as a Python module

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `VAST_API_KEY` | Endpoint API key | Required if not passed as argument |

### CLI Arguments

```
python client.py --help

Options:
  --endpoint ENDPOINT       Vast.ai endpoint name (required)
  --api-key API_KEY        Endpoint API key
  --port PORT              Local proxy port (default: 8010)
  --host HOST              Local proxy host (default: 127.0.0.1)
  --autoscaler-url URL     Autoscaler URL (default: https://run.vast.ai)
  --debug                  Enable debug logging
```

### VastClient Options

```python
VastClient(
    endpoint_name="my-endpoint",    # Required: endpoint name
    api_key="YOUR_KEY",             # Required: endpoint API key
    autoscaler_url="https://run.vast.ai",  # Optional
    instance="prod",                # Optional: prod, alpha, candidate
)
```

## Getting Your API Key

You need your **endpoint API key** (not your account API key).

### Option 1: Via Console

1. Go to https://console.vast.ai
2. Navigate to Endpoints
3. Find your endpoint
4. Copy the endpoint API key

### Option 2: Via utils/endpoint_util.py

```python
from utils.endpoint_util import Endpoint

# Get endpoint API key using account API key
endpoint_api_key = Endpoint.get_endpoint_api_key(
    endpoint_name="my-endpoint",
    account_api_key="YOUR_ACCOUNT_KEY",
    instance="prod",
)

print(endpoint_api_key)
```

## How It Works

### Traditional Flow (Complex)

```
Your Code
  ↓
Call run.vast.ai/route/ with API key
  ↓
Get worker URL + signature
  ↓
Wrap request in auth_data + payload
  ↓
POST to worker
  ↓
Parse response
```

### With PyWorker Client (Simple)

```
Your Code
  ↓
POST http://localhost:8010/endpoint
  ↓
Client handles everything
  ↓
Get response
```

The client:
1. Intercepts your request
2. Calls `/route/` to get worker assignment
3. Wraps in `auth_data` + `payload` format
4. Forwards to worker
5. Returns response

## Compatibility

Works with:
- ✅ OpenAI-compatible APIs (vLLM, Ollama, TGI)
- ✅ Text Generation Inference (TGI)
- ✅ ComfyUI
- ✅ Any HTTP API proxied through PyWorker

## Troubleshooting

### Connection Refused

**Problem:** `Connection refused to localhost:8010`

**Solution:** Make sure the proxy is running:
```bash
python client.py --endpoint my-endpoint --api-key YOUR_KEY
```

### 401 Unauthorized

**Problem:** `401 Unauthorized from autoscaler`

**Solution:** Check your API key:
- Use **endpoint API key**, not account API key
- Verify endpoint exists in console.vast.ai
- Check API key hasn't expired

### Route Failed

**Problem:** `Route failed: no workers available`

**Solution:**
- Check your endpoint has running workers
- Verify workers are healthy in console.vast.ai
- Check endpoint hasn't run out of credits

### Workload Detection

**Problem:** Client sends wrong workload

**Solution:** Specify manually:
```python
client.post("/endpoint", json={...}, workload=500.0)
```

## Advanced Usage

### Custom Routing

```python
from client import VastClient

client = VastClient(endpoint_name="my-endpoint", api_key="YOUR_KEY")

# Get routing info manually
routing = client.route(endpoint="/v1/completions", workload=500.0)
print(routing)
# {'url': 'https://worker-ip:3000', 'signature': '...', ...}

# Use routing info for custom request
# ...
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
import requests
from client import VastClient

client = VastClient(...)

# requests.request() is used internally, so standard requests options work
response = client.post("/endpoint", json={...}, timeout=60)
```

## Development

### Running Tests

```bash
# Start a test proxy
python client.py --endpoint test-endpoint --api-key test-key --debug

# In another terminal, test it
python examples/use_proxy.py
```

### Modifying the Client

The client is a single file: `client.py`

Key classes:
- `VastClient` - Core client for making requests
- `VastProxy` - Local proxy server
- `main()` - CLI entry point

## Comparison

### Without Client (Manual)

```python
import requests

# Step 1: Get worker assignment
route_response = requests.post(
    "https://run.vast.ai/route/",
    headers={"Authorization": f"Bearer {api_key}"},
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
        "model": "llama-2-7b",
        "prompt": "test",
        "max_tokens": 100,
    }
}

# Step 3: Send to worker
response = requests.post(routing["url"], json=payload)
print(response.json())
```

**Total:** ~30 lines of boilerplate

### With Client (Automatic)

```python
from client import VastClient

client = VastClient(endpoint_name="my-endpoint", api_key=api_key)

response = client.post("/v1/completions", json={
    "model": "llama-2-7b",
    "prompt": "test",
    "max_tokens": 100,
})

print(response.json())
```

**Total:** 5 lines

## License

MIT License - see LICENSE file for details.
