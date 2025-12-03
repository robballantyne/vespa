# Vespa Benchmark Modules

This directory contains benchmark functions for different backend types. Each benchmark measures the maximum throughput of a backend API to inform the autoscaler's scaling decisions.

## Available Benchmarks

### 1. OpenAI-Compatible APIs (`benchmarks.openai`)

**Supports:** vLLM, Ollama, TGI (OpenAI mode), llama.cpp

**Usage:**
```bash
export BACKEND_URL="http://localhost:8000"
export BENCHMARK="benchmarks.openai:benchmark"
export MODEL_NAME="meta-llama/Llama-2-7b-hf"
```

**API Format:**
```json
POST /v1/completions
{
  "model": "model-name",
  "prompt": "test prompt",
  "max_tokens": 500,
  "temperature": 0.7
}
```

**Workload:** Measured in tokens per second (max_tokens)

**Benchmark Strategy:**
- Warmup: 1 request with 100 tokens
- 8 benchmark runs with 10 concurrent requests
- Each request: 500 max_tokens
- Returns maximum throughput across all runs

---

### 2. Text Generation Inference (`benchmarks.tgi`)

**Supports:** HuggingFace Text Generation Inference

**Usage:**
```bash
export BACKEND_URL="http://localhost:8080"
export BENCHMARK="benchmarks.tgi:benchmark"
```

**API Format:**
```json
POST /generate
{
  "inputs": "test prompt",
  "parameters": {
    "max_new_tokens": 256,
    "temperature": 0.7
  }
}
```

**Workload:** Measured in tokens per second (max_new_tokens)

**Benchmark Strategy:**
- Warmup: 1 request with 100 tokens
- 8 benchmark runs with 10 concurrent requests
- Each request: 256 max_new_tokens
- Returns maximum throughput across all runs

---

### 3. ComfyUI Image Generation (`benchmarks.comfyui`)

**Supports:** ComfyUI

**Usage:**
```bash
export BACKEND_URL="http://localhost:8188"
export BENCHMARK="benchmarks.comfyui:benchmark"
```

**API Format:**
```json
POST /runsync
{
  "input": {
    "workflow_json": { ... }
  }
}
```

**Workload:** Calculated based on resolution and steps:
```python
workload = (width * height * steps) / 1000 + resolution_adjustment + step_adjustment
```

**Benchmark Strategy:**
- Warmup: 1 image generation (512x512, 20 steps)
- 3 benchmark runs with 1 request each (sequential, ComfyUI doesn't parallelize well)
- Each request: 512x512 image, 20 steps (~5.2 workload units)
- Returns maximum throughput across all runs

**Note:** ComfyUI benchmarks run sequentially because most ComfyUI setups can't handle parallel requests efficiently.

---

## Writing Custom Benchmarks

To create a benchmark for a new backend:

### 1. Create Your Module

```bash
touch benchmarks/myapi.py
```

### 2. Implement the Benchmark Function

```python
"""
Benchmark function for My API.

Usage:
    BENCHMARK=benchmarks.myapi:benchmark
"""
import time
import logging
import asyncio
from aiohttp import ClientSession

log = logging.getLogger(__name__)


async def benchmark(backend_url: str, session: ClientSession) -> float:
    """
    Benchmark My API.

    Args:
        backend_url: Base URL of the backend (e.g., "http://localhost:8000")
        session: aiohttp ClientSession for making requests

    Returns:
        max_throughput: Maximum workload units processed per second
    """
    endpoint = f"{backend_url}/my-endpoint"

    # 1. Warmup (optional but recommended)
    log.info("Warming up...")
    async with session.post(endpoint, json={"test": "data"}) as response:
        if response.status != 200:
            log.error("Warmup failed")
            return 1.0

    # 2. Run multiple benchmark iterations
    max_throughput = 0
    runs = 8  # Adjust based on backend speed

    for run in range(1, runs + 1):
        start = time.time()

        # 3. Send concurrent requests (adjust concurrency for your backend)
        async def run_request():
            payload = {"your": "data"}
            workload = 100  # Define your workload unit

            try:
                async with session.post(endpoint, json=payload) as response:
                    if response.status == 200:
                        return workload
                    return 0
            except Exception as e:
                log.warning(f"Request failed: {e}")
                return 0

        concurrent = 10  # Adjust concurrency
        results = await asyncio.gather(*[run_request() for _ in range(concurrent)])

        # 4. Calculate throughput
        total_workload = sum(results)
        elapsed = time.time() - start
        throughput = total_workload / elapsed

        max_throughput = max(max_throughput, throughput)

        log.info(f"Run {run}/{runs}: {throughput:.2f} workload/s")

    log.info(f"Max throughput: {max_throughput:.2f} workload/s")
    return max_throughput if max_throughput > 0 else 1.0
```

### 3. Add Load Test Support (Optional but Recommended)

Add a `get_test_request()` function to enable load testing with your benchmark:

```python
def get_test_request() -> tuple[str, dict, float]:
    """
    Get a single test request for load testing.

    Returns:
        tuple: (endpoint_path, payload, workload)
    """
    endpoint = "/my-endpoint"
    payload = {"your": "data"}
    workload = 100  # Same workload unit as benchmark

    return endpoint, payload, workload
```

### 4. Use Your Benchmark

```bash
export BENCHMARK="benchmarks.myapi:benchmark"
```

### Key Principles

1. **Warmup First:** Send a warmup request to trigger model loading
2. **Multiple Runs:** Run 3-8 iterations to find maximum throughput
3. **Concurrent Requests:** Test with realistic concurrency (1-10 requests)
4. **Return Max:** Return the maximum throughput, not average
5. **Error Handling:** Gracefully handle failures and return 1.0 as fallback
6. **Workload Units:** Choose meaningful units (tokens, pixels, requests, etc.)

### Workload Definition

Your benchmark should return throughput in **workload units per second**, where a workload unit represents the computational cost of a request.

**Examples:**
- **LLMs:** tokens/second (tokens = computational cost)
- **Image Gen:** (resolution × steps)/second
- **Simple APIs:** requests/second

The autoscaler will send the workload cost in `auth_data.cost`, which should match your benchmark's workload calculation.

---

## Testing Benchmarks

You can test a benchmark without PyWorker:

```bash
python -c "
import asyncio
from aiohttp import ClientSession
from benchmarks.openai import benchmark

async def test():
    async with ClientSession() as session:
        throughput = await benchmark('http://localhost:8000', session)
        print(f'Max throughput: {throughput} units/s')

asyncio.run(test())
"
```

Or test through PyWorker:

```bash
# Start backend
# ...

# Start PyWorker
export BACKEND_URL="http://localhost:8000"
export BENCHMARK="benchmarks.openai:benchmark"
export UNSECURED="true"
python -m workers.generic.server

# Watch logs for benchmark results
```

---

## Load Testing with Benchmarks

Each benchmark module exports a `get_test_request()` function that provides test payloads for load testing. This ensures your load tests use the same workload patterns as benchmarking.

### Using the Load Test Script

```bash
python -m lib.test_utils \
  -k YOUR_API_KEY \
  -e my-endpoint \
  -b benchmarks.openai \
  -n 100 \
  -rps 10
```

**Parameters:**
- `-k`: Your Vast.ai account API key
- `-e`: Endpoint group name
- `-b`: Benchmark module to use (benchmarks.openai, benchmarks.tgi, benchmarks.comfyui)
- `-n`: Total number of requests to send
- `-rps`: Requests per second
- `-i`: Instance (prod, alpha, candidate, local) - optional, defaults to prod

**Example: Load test OpenAI endpoint**
```bash
export MODEL_NAME="llama-2-7b"
python -m lib.test_utils \
  -k YOUR_KEY \
  -e llama-endpoint \
  -b benchmarks.openai \
  -n 50 \
  -rps 5
```

**Example: Load test TGI endpoint**
```bash
python -m lib.test_utils \
  -k YOUR_KEY \
  -e tgi-endpoint \
  -b benchmarks.tgi \
  -n 30 \
  -rps 3
```

**Example: Load test ComfyUI endpoint**
```bash
python -m lib.test_utils \
  -k YOUR_KEY \
  -e comfy-endpoint \
  -b benchmarks.comfyui \
  -n 10 \
  -rps 1
```

### Adding Load Test Support to Custom Benchmarks

When creating a custom benchmark, add a `get_test_request()` function:

```python
def get_test_request() -> tuple[str, dict, float]:
    """
    Get a single test request for load testing.

    Returns:
        tuple: (endpoint_path, payload, workload)
            - endpoint_path: API endpoint (e.g., "/my-endpoint")
            - payload: Request payload dict
            - workload: Workload cost (e.g., tokens, compute units)
    """
    endpoint = "/my-endpoint"
    payload = {
        "data": "test",
        "size": 100,
    }
    workload = 100  # Match your benchmark's workload units

    return endpoint, payload, workload
```

This ensures:
1. **Consistency**: Load tests use the same payloads as benchmarks
2. **No duplication**: Don't need separate test payload generation
3. **Correct workload**: Autoscaler gets accurate cost estimates

---

## Troubleshooting

### Benchmark Fails Immediately

**Problem:** Benchmark returns 1.0 without running

**Solutions:**
1. Check `BACKEND_URL` is correct
2. Verify backend is running: `curl $BACKEND_URL/health`
3. Check endpoint path (e.g., `/v1/completions` vs `/completions`)
4. Review logs for connection errors

### Benchmark Takes Too Long

**Problem:** Benchmark runs for several minutes

**Solutions:**
1. Reduce number of runs (default 8 → 3)
2. Reduce concurrent requests (default 10 → 5)
3. Reduce workload per request (tokens, steps, resolution)
4. This is normal for ComfyUI (image generation is slow)

### Benchmark Results Vary Widely

**Problem:** Throughput changes dramatically between runs

**Solutions:**
1. Increase number of runs to get better max value
2. Check if backend has warmup period
3. Verify system resources (GPU, RAM) are sufficient
4. Look for background processes competing for resources

### All Requests Fail

**Problem:** No successful responses in benchmark

**Solutions:**
1. Check API format matches backend expectations
2. Verify authentication/API keys if required
3. Test endpoint manually: `curl -X POST $BACKEND_URL/endpoint -d '...'`
4. Check backend logs for errors

---

## Benchmark Results

Benchmark results are saved to `.has_benchmark` file and reused on restart:

```bash
# View saved benchmark
cat .has_benchmark
# Output: 1234.56

# Force re-benchmark
rm .has_benchmark
# Run PyWorker (will re-benchmark on startup)
python server.py
```

---

## Contributing

When adding a new benchmark:

1. Follow the function signature: `async def benchmark(backend_url: str, session: ClientSession) -> float`
2. Add comprehensive docstring with usage and API format
3. Include error handling and fallback to 1.0
4. Test with real backend before submitting
5. Update this document with your benchmark details
