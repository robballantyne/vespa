# Vespa - Simplified Serverless Proxy for Vast.ai

Vespa is a lightweight, generic proxy that enables serverless compute on Vast.ai for **any** API backend without writing custom code.

## Key Features

- ✅ **Zero boilerplate** - Proxy any API without writing handlers
- ✅ **Universal compatibility** - Works with OpenAI, TGI, vLLM, Ollama, ComfyUI, or any HTTP API
- ✅ **Simple benchmarking** - One Python function to define performance
- ✅ **Full metrics** - Automatic tracking and autoscaler integration
- ✅ **All HTTP methods** - GET, POST, PUT, PATCH, DELETE
- ✅ **Streaming support** - Automatic detection and pass-through

## For Users: Simple Client

If you just want to **use** a Vast.ai endpoint (not run a worker), use the client:

```bash
# Start local proxy
python client.py --endpoint my-endpoint --api-key YOUR_KEY

# Point your app at localhost:8010
import requests
response = requests.post("http://localhost:8010/v1/completions", json={...})
```

The client handles all Vast.ai routing automatically! See [CLIENT.md](CLIENT.md) for details.

---

## For Developers: Running a Worker

### 1. Set Environment Variables

```bash
# Required
export BACKEND_URL="http://localhost:8000"  # Your backend API
export BENCHMARK="benchmarks.openai:benchmark"   # Benchmark function

# Optional
export HEALTHCHECK_ENDPOINT="/health"            # Health check path
export ALLOW_PARALLEL="true"                     # Allow concurrent requests
export MAX_WAIT_TIME="10.0"                      # Max queue time (seconds)
```

### 2. Run PyWorker

```bash
./start_server.sh
```

That's it! Vespa will:
1. Start proxying requests to your backend
2. Run the benchmark to measure throughput
3. Report metrics to the Vast.ai autoscaler

## How It Works

### Request Flow

```
Client → Vast.ai Autoscaler → PyWorker → Your Backend API
                ↓                ↓
         (calculates workload)  (tracks metrics)
```

1. **Client** sends request to Vast.ai
2. **Autoscaler** calculates workload and routes to worker
3. **PyWorker** validates signature and forwards request
4. **Backend** processes request
5. **PyWorker** streams response back to client

### No Custom Code Required!

Unlike the old architecture, you **don't need** to:
- ❌ Create a custom worker directory
- ❌ Define `ApiPayload` classes
- ❌ Define `EndpointHandler` classes
- ❌ Implement `generate_payload_json()`
- ❌ Implement `generate_client_response()`
- ❌ Calculate workload (autoscaler does this)
- ❌ Transform requests or responses

## Benchmarking

The **only** custom code is your benchmark function. This tells PyWorker how fast your backend can process requests.

### Benchmark Function Signature

```python
async def benchmark(backend_url: str, session: ClientSession) -> float:
    """
    Run performance benchmark.

    Args:
        backend_url: Base URL of your backend (e.g., "http://localhost:8000")
        session: aiohttp ClientSession for making requests

    Returns:
        max_throughput: Maximum workload units processed per second
    """
    # Your benchmark logic here
    return max_throughput
```

### Example: OpenAI API Benchmark

See `benchmarks/openai.py` for a complete example that benchmarks OpenAI-compatible APIs (vLLM, Ollama, TGI, llama.cpp).

### Using Your Benchmark

```bash
export BENCHMARK="benchmarks.openai:benchmark"
# or
export BENCHMARK="my_module.benchmarks:my_function"
```

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BACKEND_URL` | Yes | - | Backend API URL (e.g., `http://localhost:8000`) |
| `BENCHMARK` | Recommended | None | Python module path to benchmark function (e.g., `benchmarks.openai:benchmark`) |
| `BACKEND` | No | `generic` | Worker type (use `generic` for new setup) |
| `HEALTHCHECK_ENDPOINT` | No | `/health` | Health check path - defaults to `/health` if not specified |
| `READY_TIMEOUT` | No | `1200` | Seconds to wait for backend ready before failing (default: 20 minutes) |
| `ALLOW_PARALLEL` | No | `true` | Allow concurrent requests |
| `MAX_WAIT_TIME` | No | `10.0` | Max queue wait time before rejecting (seconds) |
| `WORKER_PORT` | No | `3000` | Port to listen on |
| `UNSECURED` | No | `false` | Disable signature verification (dev only) |

### Vast.ai Configuration

These are set by Vast.ai automatically:

| Variable | Description |
|----------|-------------|
| `MASTER_TOKEN` | Authentication token for autoscaler |
| `REPORT_ADDR` | Autoscaler URL for metrics reporting |
| `CONTAINER_ID` | Unique worker instance ID |
| `PUBLIC_IPADDR` | Public IP address |

## Example Configurations

### vLLM / Ollama / OpenAI-Compatible

```bash
export BACKEND_URL="http://localhost:8000"
export BENCHMARK="benchmarks.openai:benchmark"
export MODEL_NAME="meta-llama/Llama-2-7b-hf"
export HEALTHCHECK_ENDPOINT="/health"
```

### Text Generation Inference (TGI)

```bash
export BACKEND_URL="http://localhost:8080"
export BENCHMARK="benchmarks.openai:benchmark"  # TGI also supports OpenAI format
export HEALTHCHECK_ENDPOINT="/health"
```

### Any Custom API

```bash
export BACKEND_URL="http://localhost:5000"
export BENCHMARK="my_benchmarks:my_api_benchmark"
export HEALTHCHECK_ENDPOINT="/status"
export ALLOW_PARALLEL="false"  # If your API doesn't support concurrency
```

## Comparison: Old vs New

### Old Architecture ❌

```
workers/
├── openai/          # Custom worker for OpenAI
│   ├── server.py    # 60 lines of boilerplate
│   └── data_types/
│       └── server.py  # 200 lines of handlers
├── tgi/             # Custom worker for TGI
│   ├── server.py    # 60 lines of boilerplate
│   └── data_types/
│       └── server.py  # 150 lines of handlers
└── comfyui/         # Custom worker for ComfyUI
    ├── server.py    # 60 lines of boilerplate
    └── data_types/
        └── server.py  # 300 lines of handlers
```

**Problems:**
- 410+ lines of code per API
- Hardcoded endpoints
- POST-only
- Complex payload transformations
- Manual workload calculation

### New Architecture ✅

```
pyworker/
├── server.py        # 100 lines - works for ALL APIs!
├── lib/             # Core framework (backend, metrics, etc.)
└── benchmarks/      # Just benchmark functions
    ├── openai.py    # 130 lines
    ├── tgi.py       # 140 lines
    └── comfyui.py   # 240 lines
```

**Benefits:**
- **10x less code** - 80-240 lines vs 410+ lines per API
- **Universal** - Works with any HTTP API
- **Simple** - Just write 1 benchmark function
- **Flexible** - All HTTP methods, any endpoint
- **Flat structure** - No complex directory hierarchies

## Development

### Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Set env vars
export BACKEND_URL="http://localhost:8000"
export BENCHMARK="benchmarks.openai:benchmark"
export UNSECURED="true"  # Skip signature verification for local testing

# Run
python server.py
```

### Testing Without Autoscaler

**Passthrough Mode (Recommended):** When `UNSECURED=true`, just send requests directly!

```bash
# Simple! Just like calling your backend API
curl -X POST http://localhost:3000/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "my-model",
    "prompt": "Hello",
    "max_tokens": 100
  }'
```

Vespa automatically wraps your request for metrics tracking.

**Production Format (Optional):** Test with full auth_data wrapper:

```bash
curl -X POST http://localhost:3000/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "auth_data": {
      "cost": "500",
      "endpoint": "/v1/completions",
      "reqnum": 1,
      "request_idx": 1,
      "signature": "",
      "url": ""
    },
    "payload": {
      "model": "my-model",
      "prompt": "Hello",
      "max_tokens": 100
    }
  }'
```

## Architecture Details

### Metrics Tracking

Vespa automatically tracks and reports:

- **Request metrics**: workload, status, duration
- **Model metrics**: throughput, queue depth, errors
- **System metrics**: disk usage, loading time

Reported every second to Vast.ai autoscaler for:
- Dynamic scaling decisions
- Cost calculation
- Health monitoring

### Streaming

Vespa automatically detects streaming responses by checking:
- Content-Type: `text/event-stream`
- Content-Type: `application/x-ndjson`
- Transfer-Encoding: `chunked`
- Content-Type contains `stream`

Streams are passed through chunk-by-chunk without buffering.

## Client Usage

Want to call Vast.ai endpoints from your code? Use the client!

### Quick Start

```bash
# Start proxy server
python client.py --endpoint my-endpoint --api-key YOUR_KEY
```

Now use `localhost:8010` in your code:

```python
import requests

# Works with any framework!
response = requests.post(
    "http://localhost:8010/v1/chat/completions",
    json={"messages": [{"role": "user", "content": "Hello!"}]},
)
```

### Or Use as Module

```python
from client import VastClient

client = VastClient(endpoint_name="my-endpoint", api_key="YOUR_KEY")
response = client.post("/v1/completions", json={...})
```

See **[CLIENT.md](CLIENT.md)** for complete documentation.

---

## Troubleshooting

### Benchmark Fails

**Error:** `Benchmark failed: <error>`

**Solution:** Check your benchmark function:
```bash
# Test benchmark directly
python -c "
import asyncio
from aiohttp import ClientSession
from benchmarks.openai import benchmark

async def test():
    async with ClientSession('http://localhost:8000') as session:
        result = await benchmark('http://localhost:8000', session)
        print(f'Throughput: {result}')

asyncio.run(test())
"
```

### Backend Not Responding

**Error:** `Request error: Cannot connect to host localhost:8000`

**Solution:**
1. Check `BACKEND_URL` is correct
2. Ensure backend is running: `curl $BACKEND_URL/health`
3. Check firewall/network settings

## Community & Support

Join the conversation and get help:

*   **Vast.ai Discord:** [https://discord.gg/Pa9M29FFye](https://discord.gg/Pa9M29FFye)
*   **Vast.ai Subreddit:** [https://reddit.com/r/vastai/](https://reddit.com/r/vastai/)

## License

MIT License - see LICENSE file for details.
