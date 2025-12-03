# Vespa File Structure

## Overview

Vespa now has a clean, flat structure with minimal files. The entire implementation consists of:
- **1 entry point** - `server.py` (120 lines)
- **3 benchmark modules** - OpenAI, TGI, ComfyUI (507 lines total)
- **Core framework** - Reusable library code (1,287 lines)

## Directory Structure

```
vespa/
├── server.py                    # Worker entry point (120 lines)
├── client.py                    # Client proxy (300 lines)
│
├── lib/                         # Core framework (1,287 lines)
│   ├── backend.py              # Request handling, metrics, benchmarking
│   ├── data_types.py           # Data models (AuthData, Metrics, etc.)
│   ├── metrics.py              # Metrics tracking and autoscaler reporting
│   ├── server.py               # aiohttp server setup
│   └── test_utils.py           # Load testing utilities
│
├── benchmarks/                  # User-written benchmarks (507 lines)
│   ├── openai.py               # OpenAI/vLLM/Ollama/llama.cpp (132 lines)
│   ├── tgi.py                  # Text Generation Inference (141 lines)
│   └── comfyui.py              # ComfyUI image generation (233 lines)
│
├── utils/                       # Optional utilities
│   ├── endpoint_util.py        # Vast.ai endpoint discovery
│   └── ssl.py                  # SSL certificate handling
│
├── start_server.sh             # Startup script
├── requirements.txt            # Python dependencies
│
├── README.md                   # Main documentation
├── MIGRATION.md                # Migration guide from old architecture
├── BENCHMARKS.md               # Benchmark writing guide
└── STRUCTURE.md                # This file
```

## File Descriptions

### `server.py` (120 lines)

The worker entry point. Loads configuration from environment variables and starts the proxy server.

**Key functions:**
- `load_benchmark_function()` - Dynamically imports benchmark function
- Route definitions - Catch-all routes for all HTTP methods
- Server startup

**Usage:**
```bash
export BACKEND_URL="http://localhost:8000"
export BENCHMARK="benchmarks.openai:benchmark"
python server.py
```

### `client.py` (300 lines)

Simple client for calling Vast.ai endpoints. Abstracts away routing complexity.

**Key classes:**
- `VastClient` - Python module for making requests
- `VastProxy` - Local HTTP proxy server

**Usage as proxy:**
```bash
python client.py --endpoint my-endpoint --api-key YOUR_KEY
# Then use http://localhost:8010 in your code
```

**Usage as module:**
```python
from client import VastClient
client = VastClient(endpoint_name="my-endpoint", api_key="YOUR_KEY")
response = client.post("/v1/completions", json={...})
```

The client handles:
- Calling `/route/` to get worker assignment
- Wrapping requests in `auth_data` + `payload` format
- Forwarding to assigned worker
- Auto-detecting workload from common fields

### `lib/backend.py` (456 lines)

Core proxy logic. Handles request forwarding, authentication, and metrics.

**Key features:**
- Pass-through request forwarding (all HTTP methods)
- Signature verification with autoscaler public key
- Rate limiting based on queue depth
- Streaming response detection and forwarding
- Automatic benchmarking on startup
- Healthcheck monitoring

**Changed from old architecture:**
- ❌ Removed: `EndpointHandler` abstraction
- ❌ Removed: `ApiPayload` transformation
- ❌ Removed: Log file tailing
- ✅ Added: Universal request forwarding
- ✅ Added: Dynamic benchmark loading

### `lib/data_types.py` (175 lines)

Data models used throughout the system.

**Key classes:**
- `AuthData` - Authentication data from autoscaler
- `RequestMetrics` - Per-request tracking
- `ModelMetrics` - Aggregate metrics (workload, throughput, etc.)
- `SystemMetrics` - System-level metrics (disk, loading time)
- `AutoScalerData` - Data reported to autoscaler

**Changed from old architecture:**
- ❌ Removed: `ApiPayload` abstract class
- ❌ Removed: `EndpointHandler` abstract class
- ❌ Removed: `BenchmarkResult` class
- ❌ Removed: `LogAction` enum

### `lib/metrics.py` (286 lines)

Metrics collection and autoscaler reporting. **Unchanged** - all reporting preserved.

**Key features:**
- Tracks request lifecycle (start, success, error, cancel, reject)
- Aggregates workload metrics
- Reports to autoscaler every 1 second
- Handles request deletion notifications

### `lib/server.py` (60 lines)

Simple aiohttp server setup. Minimal and unchanged.

### `benchmarks/*.py` (507 lines total)

User-written benchmark functions. **This is the only custom code needed per backend.**

Each benchmark:
- Takes `backend_url` and `session` as parameters
- Sends test requests to measure throughput
- Returns maximum throughput in workload units/second

**Example:**
```python
async def benchmark(backend_url: str, session: ClientSession) -> float:
    # Run 8 iterations of benchmark
    # Return max throughput
    return max_throughput
```

## What Changed From Old Architecture

### Removed (~1,300 lines)

```
workers/
├── openai/
│   ├── server.py                    # ❌ 60 lines
│   └── data_types/server.py         # ❌ 200 lines
├── tgi/
│   ├── server.py                    # ❌ 60 lines
│   └── data_types.py                # ❌ 150 lines
├── comfyui/
│   ├── server.py                    # ❌ 60 lines
│   └── data_types/server.py         # ❌ 350 lines
├── comfyui-json/
│   └── ...                          # ❌ 300 lines
└── hello_world/
    └── ...                          # ❌ 150 lines
```

**Each backend required:**
- Custom `server.py` with route definitions
- Custom `ApiPayload` subclass
- Custom `EndpointHandler` subclass
- `generate_payload_json()` method
- `generate_client_response()` method
- `count_workload()` method
- Log parsing configuration

### New Structure (~1,914 lines)

```
pyworker/
├── server.py                        # ✅ 120 lines (universal!)
├── lib/                             # ✅ 1,287 lines (framework)
└── benchmarks/                      # ✅ 507 lines (user code)
    ├── openai.py
    ├── tgi.py
    └── comfyui.py
```

**Each backend requires:**
- ✅ One benchmark function (~100-200 lines)
- ✅ That's it!

## Code Metrics

| Component | Lines | Description |
|-----------|-------|-------------|
| `server.py` | 120 | Main entry point |
| `lib/backend.py` | 456 | Core proxy logic |
| `lib/data_types.py` | 175 | Data models |
| `lib/metrics.py` | 286 | Metrics tracking |
| `lib/server.py` | 60 | Server setup |
| `lib/test_utils.py` | 310 | Testing utilities |
| **Framework Total** | **1,407** | **Reusable across all backends** |
| | | |
| `benchmarks/openai.py` | 132 | OpenAI benchmark |
| `benchmarks/tgi.py` | 141 | TGI benchmark |
| `benchmarks/comfyui.py` | 233 | ComfyUI benchmark |
| **Benchmarks Total** | **506** | **User-written code** |
| | | |
| **Grand Total** | **1,913** | **Complete implementation** |

### Comparison

| Metric | Old Architecture | New Architecture | Change |
|--------|-----------------|------------------|--------|
| Code per backend | ~410 lines | ~120 lines | **-71%** |
| Total for 3 backends | ~1,230 lines | 506 lines | **-59%** |
| Framework code | Duplicated | Shared (1,407) | Reusable |
| New backend effort | ~410 lines | ~120 lines | **-71%** |

## Adding a New Backend

### Old Way

1. Create `workers/myapi/` directory
2. Create `workers/myapi/server.py` (~60 lines)
3. Create `workers/myapi/data_types.py` (~200+ lines)
4. Implement `ApiPayload` subclass
5. Implement `EndpointHandler` subclass
6. Define `generate_payload_json()`
7. Define `generate_client_response()`
8. Define `count_workload()`
9. Define log parsing rules
10. Update `start_server.sh`

**Total effort:** ~410 lines of boilerplate

### New Way

1. Create `benchmarks/myapi.py`
2. Write one function:
   ```python
   async def benchmark(backend_url, session):
       # Your benchmark logic
       return max_throughput
   ```

**Total effort:** ~100-200 lines

## Environment Variables

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `BACKEND_URL` | Backend API URL | `http://localhost:8000` |
| `BENCHMARK` | Benchmark module path | `benchmarks.openai:benchmark` |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `HEALTHCHECK_ENDPOINT` | `None` | Health check path |
| `ALLOW_PARALLEL` | `true` | Allow concurrent requests |
| `MAX_WAIT_TIME` | `10.0` | Max queue time (seconds) |
| `WORKER_PORT` | `3000` | Port to listen on |
| `UNSECURED` | `false` | Disable auth (dev only) |

### Vast.ai (Auto-configured)

| Variable | Description |
|----------|-------------|
| `MASTER_TOKEN` | Autoscaler auth token |
| `REPORT_ADDR` | Autoscaler URL |
| `CONTAINER_ID` | Worker instance ID |
| `PUBLIC_IPADDR` | Public IP address |

## Benefits of Flat Structure

### Before (workers/ directory)

```
workers/
├── openai/
│   ├── server.py
│   ├── data_types/
│   │   └── server.py
│   └── __init__.py
├── tgi/
│   ├── server.py
│   ├── data_types.py
│   └── __init__.py
└── ... (more backends)
```

**Problems:**
- Deep nesting (`workers/openai/data_types/server.py`)
- Confusing imports (`from workers.openai.data_types.server import ...`)
- Unclear which files to edit
- Lots of boilerplate `__init__.py` files

### After (flat structure)

```
pyworker/
├── server.py              # Entry point (obvious!)
├── lib/                   # Framework (don't touch)
└── benchmarks/            # Your code goes here
    ├── openai.py
    └── myapi.py           # Add your benchmark here
```

**Benefits:**
- ✅ Clear entry point (`server.py`)
- ✅ Simple imports (`from lib.backend import Backend`)
- ✅ Obvious where to add code (`benchmarks/`)
- ✅ No deep nesting
- ✅ Minimal `__init__.py` files

## Running PyWorker

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment
export BACKEND_URL="http://localhost:8000"
export BENCHMARK="benchmarks.openai:benchmark"
export UNSECURED="true"

# Run
python server.py
```

### Production (Vast.ai)

```bash
# Via start_server.sh (automatically sets up venv, SSL, etc.)
./start_server.sh
```

The startup script handles:
- Python virtual environment setup
- SSL certificate generation
- Environment variable validation
- Log file rotation
- Error reporting to autoscaler

## Summary

The new flat structure is:
- **Simpler** - Clear entry point, minimal files
- **More maintainable** - Less code to maintain
- **More flexible** - Works with any API
- **Easier to understand** - Obvious file organization
- **Faster to extend** - Just add a benchmark function

**Old architecture:** 410 lines per backend
**New architecture:** 120 lines per backend
**Savings:** 71% less code
