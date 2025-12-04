# Vespa - Universal Serverless Proxy for Vast.ai

Vespa is a lightweight HTTP proxy that enables serverless compute on Vast.ai for **any** backend API without custom code.

## Features

- **Universal** - Works with any HTTP API (OpenAI, vLLM, TGI, Ollama, ComfyUI, custom APIs)
- **Zero boilerplate** - No custom handlers, transformations, or payload classes
- **All HTTP methods** - GET, POST, PUT, PATCH, DELETE
- **Streaming** - Automatic detection and pass-through
- **Metrics** - Automatic tracking and autoscaler integration
- **Simple benchmarking** - One async function defines performance

---

## Quick Start

### Running on Vast.ai

```bash
export VESPA_BACKEND_URL="http://localhost:8000"
export VESPA_BENCHMARK="benchmarks.openai:benchmark"
./start_server.sh
```

### Running Locally

```bash
export VESPA_BACKEND_URL="http://localhost:8000"
export VESPA_BENCHMARK="benchmarks.openai:benchmark"
export VESPA_WORKER_PORT="3000"
export VESPA_UNSECURED="true"
python server.py
```

Test it:
```bash
curl -X POST http://localhost:3000/v1/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "my-model", "prompt": "Hello", "max_tokens": 100}'
```

---

## Configuration

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `VESPA_BACKEND_URL` | Backend API base URL | `http://localhost:8000` |
| `VESPA_WORKER_PORT` | Port for Vespa to listen on | `3000` |

**Note:** On Vast.ai, `VESPA_WORKER_PORT` has a default of `3000` set by `start_server.sh`.

### Core Options

| Variable | Default | Description |
|----------|---------|-------------|
| `VESPA_BENCHMARK` | None | Python module path to benchmark function<br/>Format: `module.path:function_name`<br/>Example: `benchmarks.openai:benchmark`<br/>If not provided, uses default throughput of 1.0 |
| `VESPA_HEALTHCHECK_ENDPOINT` | None | Health check path (e.g., `/health`)<br/>Falls back to `/health` if not set |
| `VESPA_ALLOW_PARALLEL` | `true` | Allow concurrent request processing |
| `VESPA_MAX_WAIT_TIME` | `10.0` | Max queue wait time (seconds) before rejecting (HTTP 429) |
| `VESPA_READY_TIMEOUT_INITIAL` | `1200` | Max seconds to wait for backend ready on initial startup when models need downloading (20 minutes) |
| `VESPA_READY_TIMEOUT_RESUME` | `300` | Max seconds to wait for backend ready when resuming from stopped state with models on disk (5 minutes) |
| `VESPA_UNSECURED` | `false` | Disable signature verification (**local dev only**) |
| `VESPA_USE_SSL` | `false` (direct) / `true` (Vast.ai) | Enable SSL/TLS. Default is `false` when running `server.py` directly, `true` when using `start_server.sh` |
| `VESPA_LOG_LEVEL` | `INFO` | Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL |

### Advanced Tunables

**Connection Pooling:**
| Variable | Default | Description |
|----------|---------|-------------|
| `VESPA_CONNECTION_LIMIT` | `100` | Max total connections to backend |
| `VESPA_CONNECTION_LIMIT_PER_HOST` | `20` | Max connections per backend host |
| `VESPA_METRICS_CONNECTION_LIMIT` | `8` | Max total connections for metrics |
| `VESPA_METRICS_CONNECTION_LIMIT_PER_HOST` | `4` | Max connections per metrics host |

**Healthcheck Tuning:**
| Variable | Default | Description |
|----------|---------|-------------|
| `VESPA_HEALTHCHECK_RETRY_INTERVAL` | `5` | Seconds between healthcheck retries during startup |
| `VESPA_HEALTHCHECK_POLL_INTERVAL` | `10` | Seconds between periodic healthchecks after startup |
| `VESPA_HEALTHCHECK_TIMEOUT` | `10` | Timeout (seconds) for healthcheck requests |
| `VESPA_HEALTHCHECK_CONSECUTIVE_FAILURES` | `3` | Number of consecutive failures before marking backend as errored |

**Metrics & Reporting:**
| Variable | Default | Description |
|----------|---------|-------------|
| `VESPA_METRICS_UPDATE_INTERVAL` | `1` | Seconds between metrics updates to autoscaler |
| `VESPA_DELETE_REQUESTS_INTERVAL` | `1` | Seconds between delete request cleanup |
| `VESPA_METRICS_RETRY_DELAY` | `2` | Seconds between retry attempts |
| `VESPA_METRICS_MAX_RETRIES` | `3` | Max retry attempts for metrics reporting |
| `VESPA_METRICS_TIMEOUT` | `10` | Timeout (seconds) for metrics HTTP requests |

**Security:**
| Variable | Default | Description |
|----------|---------|-------------|
| `VESPA_PUBKEY_TIMEOUT` | `10` | Timeout (seconds) for fetching public key |
| `VESPA_PUBKEY_MAX_RETRIES` | `3` | Max attempts before falling back to unsecured mode |

**Other:**
| Variable | Default | Description |
|----------|---------|-------------|
| `VESPA_BENCHMARK_CACHE_FILE` | `.has_benchmark` | File path to cache benchmark results |

### Vast.ai Variables (Set by Platform)

These are automatically set by Vast.ai:

| Variable | Description |
|----------|-------------|
| `MASTER_TOKEN` | Authentication token for autoscaler |
| `REPORT_ADDR` | Autoscaler URL for metrics reporting (comma-separated) |
| `CONTAINER_ID` | Unique worker instance ID |
| `PUBLIC_IPADDR` | Public IP address |
| `VAST_TCP_PORT_*` | Mapped public ports |

### Backend Variables (Not Vespa-Specific)

These are used by backend servers, not Vespa configuration:

| Variable | Used By | Description |
|----------|---------|-------------|
| `MODEL_NAME` | vLLM, Ollama, TGI | Model name for API requests |
| `HF_TOKEN` | HuggingFace models | Authentication token |

---

## Example Configurations

### vLLM / Ollama

```bash
export VESPA_BACKEND_URL="http://localhost:8000"
export VESPA_BENCHMARK="benchmarks.openai:benchmark"
export MODEL_NAME="meta-llama/Llama-2-7b-hf"
```

### Text Generation Inference (TGI)

```bash
export VESPA_BACKEND_URL="http://localhost:8080"
export VESPA_BENCHMARK="benchmarks.openai:benchmark"
```

### Custom API (Non-Concurrent)

```bash
export VESPA_BACKEND_URL="http://localhost:5000"
export VESPA_BENCHMARK="my_module:my_benchmark"
export VESPA_HEALTHCHECK_ENDPOINT="/status"
export VESPA_ALLOW_PARALLEL="false"
```

---

## Benchmarking

Vespa requires a benchmark function to measure backend throughput for autoscaling.

### Benchmark Function Signature

```python
async def benchmark(backend_url: str, session: ClientSession) -> float:
    """
    Measure backend throughput.

    Args:
        backend_url: Base URL of backend (e.g., "http://localhost:8000")
        session: aiohttp ClientSession for making requests

    Returns:
        max_throughput: Maximum workload units per second
    """
    # Run performance tests
    return max_throughput
```

### Built-in Benchmarks

- **`benchmarks.openai:benchmark`** - OpenAI-compatible APIs (vLLM, Ollama, TGI, llama.cpp)
- **`benchmarks.tgi:benchmark`** - Text Generation Inference
- **`benchmarks.comfyui:benchmark`** - ComfyUI image generation

See [BENCHMARKS.md](BENCHMARKS.md) for writing custom benchmarks.

---

## How It Works

### Request Flow

```
Client → Vast.ai Autoscaler → Vespa → Backend API
              ↓                  ↓
       (routes & signs)    (validates & streams)
```

1. Client sends request to Vast.ai endpoint
2. Autoscaler calculates workload, signs request, routes to worker
3. Vespa validates signature, forwards to backend
4. Backend processes request
5. Vespa streams response back to client, updates metrics

### Metrics Tracked

- **Requests**: workload served/received/cancelled/errored/rejected
- **Model**: throughput, queue depth, wait time, errors
- **System**: disk usage, loading time

Reported every second to autoscaler for dynamic scaling and health monitoring.

### Streaming Detection

Vespa automatically detects streaming responses by:
- Content-Type: `text/event-stream` or `application/x-ndjson`
- Transfer-Encoding: `chunked`
- Content-Type contains `stream`

Streams are passed through chunk-by-chunk without buffering.

---

## Local Development

### Testing in Passthrough Mode

When `VESPA_UNSECURED=true`, send requests directly without auth_data wrapper:

```bash
export VESPA_BACKEND_URL="http://localhost:8000"
export VESPA_BENCHMARK="benchmarks.openai:benchmark"
export VESPA_WORKER_PORT="3000"
export VESPA_UNSECURED="true"
python server.py
```

```bash
# Simple passthrough
curl -X POST http://localhost:3000/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "my-model",
    "prompt": "Hello",
    "max_tokens": 100
  }'
```

### Testing in Production Format

Test with full auth_data wrapper (for debugging autoscaler integration):

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

---

## Client Usage

Want to call Vast.ai endpoints from your code? Use the client proxy - it's now easier than ever!

### Interactive Mode (Easiest)

```bash
# Just run it - prompts for everything
python client.py
```

It will:
1. Prompt for your account API key
2. Show all your endpoints
3. Auto-fetch the endpoint key
4. Start the proxy

### One Command

```bash
# With account key (auto-fetches endpoint key)
python client.py --endpoint my-endpoint --account-key YOUR_ACCOUNT_KEY

# List available endpoints
python client.py --list --account-key YOUR_ACCOUNT_KEY
```

### Environment Variables

```bash
export VAST_ACCOUNT_KEY="your-key"
export VAST_ENDPOINT="my-endpoint"
python client.py  # Just works!
```

### Using the Proxy

```python
import requests

# Point your app at localhost:8010
response = requests.post(
    "http://localhost:8010/v1/completions",
    json={"model": "my-model", "prompt": "Hello"}
)
```

See [CLIENT.md](CLIENT.md) for complete documentation.

---

## Troubleshooting

### Backend Connection Error

**Error:** `Cannot connect to host localhost:8000`

**Solutions:**
1. Verify `VESPA_BACKEND_URL` is correct
2. Ensure backend is running: `curl $VESPA_BACKEND_URL/health`
3. Check firewall/network settings

### Benchmark Fails

**Error:** `Benchmark failed: <error>`

**Solutions:**
1. Verify backend is responding to health checks
2. Check benchmark function matches your API format
3. Test benchmark directly:
```bash
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

### Worker Not Ready

**Error:** `Backend failed to become ready after N seconds`

**Solutions:**
1. Increase `VESPA_READY_TIMEOUT_INITIAL` for slow-loading models on initial startup, or `VESPA_READY_TIMEOUT_RESUME` for slow loading on resume
2. Verify `VESPA_HEALTHCHECK_ENDPOINT` returns HTTP 200 when ready
3. Check backend logs for errors

---

## Architecture

### File Structure

```
vespa/
├── server.py              # Entry point (120 lines)
├── lib/
│   ├── backend.py         # Request handling & proxy logic
│   ├── metrics.py         # Metrics tracking & reporting
│   ├── data_types.py      # Data structures
│   └── server.py          # aiohttp server setup
├── benchmarks/            # Benchmark functions
│   ├── openai.py
│   ├── tgi.py
│   └── comfyui.py
└── start_server.sh        # Production startup script
```

### Why Vespa?

**Old Architecture Problems:**
- 400+ lines of boilerplate per API type
- Hardcoded endpoints
- Complex payload transformations
- Manual workload calculations
- POST-only

**Vespa Solution:**
- Universal proxy works with any HTTP API
- No custom code except benchmark function
- Automatic streaming detection
- All HTTP methods supported
- 80% less code

---

## Resources

- **Vast.ai Discord:** https://discord.gg/Pa9M29FFye
- **Vast.ai Subreddit:** https://reddit.com/r/vastai/
- **Benchmark Guide:** [BENCHMARKS.md](BENCHMARKS.md)
- **Client Guide:** [CLIENT.md](CLIENT.md)
- **Migration Guide:** [MIGRATION.md](MIGRATION.md)

## License

MIT License - see LICENSE file for details.
