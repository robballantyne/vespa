# Claude Context: Vespa - Universal Serverless Proxy for Vast.ai

> **IMPORTANT**: When making ANY changes to this codebase, you MUST update this file to reflect those changes. This file is the source of truth for understanding the architecture, patterns, and important considerations.

## Project Overview

Vespa is a lightweight, universal HTTP proxy that enables serverless compute on Vast.ai for **any** API backend without custom code. It sits between the Vast.ai autoscaler and any backend API (OpenAI, vLLM, TGI, ComfyUI, or custom APIs), forwarding requests transparently while tracking metrics.

### Key Philosophy
- **Zero transformation**: Requests/responses pass through unchanged
- **Universal compatibility**: Works with any HTTP API
- **Minimal custom code**: Only benchmark functions need to be written
- **Metrics-driven**: Automatic tracking and autoscaler integration

## Architecture

### Request Flow
```
Client → Vast.ai Autoscaler → Vespa (PyWorker) → Backend API
              ↓                       ↓
       (routes & signs)      (validates & tracks)
```

1. **Client** sends request to Vast.ai endpoint
2. **Autoscaler** calculates workload, signs request, routes to worker
3. **Vespa** validates signature, forwards to backend, streams response
4. **Backend** processes request (model inference, etc.)
5. **Vespa** streams response back to client, updates metrics

### Component Architecture

```
server.py                  # Entry point, loads config and benchmark
├── lib/backend.py         # Core proxy logic and request handling
│   ├── session           # Shared aiohttp ClientSession for backend
│   ├── healthcheck       # Backend health monitoring
│   └── handlers          # Request forwarding and streaming
├── lib/metrics.py         # Metrics tracking and autoscaler reporting
├── lib/data_types.py      # Data structures (AuthData, RequestMetrics, etc.)
└── benchmarks/            # Benchmark functions (user-provided)
    ├── openai.py
    ├── tgi.py
    └── comfyui.py
```

## Core Components

### 1. Backend (`lib/backend.py`)

**Primary responsibility**: Forward HTTP requests to backend API without transformation.

**Key features**:
- **Single shared session**: Uses one `ClientSession` (cached_property) for all requests to backend
  - **IMPORTANT**: This is safe for concurrent use - aiohttp guarantees no response mixing
  - Connection pooling with `force_close=True` for long-running jobs
  - Separate `healthcheck_session` for isolation from API requests

- **Universal request handler**: `create_handler()` creates handlers that forward any HTTP method (GET, POST, PUT, PATCH, DELETE)

- **Streaming support**: Automatically detects and streams responses based on:
  - Content-Type: `text/event-stream` or `application/x-ndjson`
  - Transfer-Encoding: `chunked`
  - Content-Type contains "stream"

- **Startup sequence**:
  1. Wait for backend ready via healthcheck polling (`__wait_for_backend_ready`)
  2. Run benchmark function to measure throughput
  3. Report max_throughput to autoscaler
  4. Start accepting requests

- **Request lifecycle**:
  1. Parse `auth_data` and `payload` from request body (passthrough mode: if `UNSECURED=true` and no auth_data, treat entire body as payload)
  2. Validate signature (unless `UNSECURED=true`)
  3. Check queue wait time < `MAX_WAIT_TIME`
  4. Acquire semaphore if `ALLOW_PARALLEL=false`
  5. Forward request to backend
  6. Stream/pass response back to client
  7. Update metrics

**Important fields**:
- `model_server_url`: Backend API base URL
- `benchmark_func`: Async function that measures throughput
- `healthcheck_endpoint`: Health check path (defaults to `/health`)
- `allow_parallel_requests`: Enable concurrent request handling (default: true)
- `max_wait_time`: Max queue time before rejecting (default: 10s)
- `ready_timeout`: Max time to wait for backend ready (default: 1200s / 20 minutes)

### 2. Metrics (`lib/metrics.py`)

**Primary responsibility**: Track request metrics and report to Vast.ai autoscaler.

**Metrics tracked**:
- **Request metrics**: workload served/received/cancelled/errored/rejected
- **Model metrics**: throughput, queue depth, current load, wait time
- **System metrics**: disk usage, loading time

**Reporting**:
- Updates sent every 1 second to autoscaler
- Sends to `REPORT_ADDR` (comma-separated list)
- Includes workload calculations for autoscaling decisions

**Request lifecycle tracking**:
1. `_request_start()`: Called when request begins
2. `_request_success()` / `_request_errored()` / `_request_canceled()`: Called based on outcome
3. `_request_end()`: Called when request completes
4. Metrics batched and sent to autoscaler

**Important**: Workload comes from autoscaler in `auth_data.cost`, not calculated by Vespa.

### 3. Data Types (`lib/data_types.py`)

**AuthData**: Authentication/routing data from autoscaler
- `cost`: Workload cost (used as workload metric)
- `endpoint`: Target endpoint path
- `reqnum`: Request number (unique ID)
- `request_idx`: Request index
- `signature`: PKCS#1 signature for verification
- `url`: Original URL

**RequestMetrics**: Per-request tracking
- `request_idx`, `reqnum`: Request identifiers
- `workload`: Cost from auth_data
- `status`: "Created" → "Started" → "Success"/"Error"/"Cancelled"/"Rejected"
- `success`: Boolean outcome

**ModelMetrics**: Aggregated metrics for the model
- `workload_*`: Counters for served/received/cancelled/errored/rejected
- `max_throughput`: From benchmark function
- `wait_time`: Calculated as `sum(pending_workloads) / max_throughput`

**SystemMetrics**: System-level tracking
- `model_loading_time`: Time to complete benchmark
- `additional_disk_usage`: Disk usage changes

### 4. Server (`lib/server.py`)

**Primary responsibility**: aiohttp server setup and error handling.

**Key features**:
- SSL support via `USE_SSL` env var
- Concurrent execution of web server and background tasks (`_start_tracking()`)
- Beacon mode on failure: continuously reports errors to autoscaler

**Startup**:
```python
gather(
    site.start(),              # Start web server
    backend._start_tracking()  # Start metrics and healthcheck
)
```

**Background tasks** (`_start_tracking`):
- Runs `__run_benchmark_on_startup()` first to completion (wait for ready, run benchmark once)
- Then starts infinite background loops:
  - `metrics._send_metrics_loop()`: Report metrics every 1s
  - `__healthcheck()`: Monitor backend health every 10s
  - `metrics._send_delete_requests_loop()`: Clean up completed requests

## Environment Variables

### Required
- `MODEL_SERVER_URL`: Backend API base URL (e.g., `http://localhost:8000`)

### Optional (Application)
- `LOG_LEVEL`: Logging level - DEBUG, INFO, WARNING, ERROR, CRITICAL (default: `INFO`)
- `BENCHMARK`: Python module path to benchmark function (e.g., `benchmarks.openai:benchmark`)
- `HEALTHCHECK_ENDPOINT`: Health check path (defaults to `/health` if not set)
- `READY_TIMEOUT`: Seconds to wait for backend ready (default: `1200`)
- `ALLOW_PARALLEL`: Allow concurrent requests (default: `true`)
- `MAX_WAIT_TIME`: Max queue wait time in seconds (default: `10.0`)
- `WORKER_PORT`: Port to listen on (default: `3000`)
- `UNSECURED`: Disable signature verification for local dev (default: `false`)
- `USE_SSL`: Enable SSL/TLS (default: `false`)

### Set by Vast.ai
- `MASTER_TOKEN`: Authentication token for autoscaler
- `REPORT_ADDR`: Autoscaler URL for metrics reporting (comma-separated)
- `CONTAINER_ID`: Unique worker instance ID
- `PUBLIC_IPADDR`: Public IP address
- `VAST_TCP_PORT_{port}`: Mapped public port

## Important Patterns and Conventions

### 1. Healthcheck-Based Startup

**Pattern**: Always wait for backend health before benchmarking
```python
await self.__wait_for_backend_ready()  # Poll until HTTP 200
await self.benchmark_func(...)          # Then benchmark
```

**Why**: Models can take minutes to load. Hardcoded delays are unreliable.

**Behavior**:
- Polls healthcheck endpoint every 5 seconds
- Uses `HEALTHCHECK_ENDPOINT` if set, otherwise defaults to `/health`
- Fails worker if no response within `READY_TIMEOUT`
- Marks backend as errored and reports to autoscaler

### 2. Shared Session Safety

**Pattern**: Single `ClientSession` shared across all requests
```python
@cached_property
def session(self):
    connector = TCPConnector(force_close=True, enable_cleanup_closed=True)
    return ClientSession(self.model_server_url, timeout=..., connector=connector)
```

**Why safe**:
- aiohttp `ClientSession` is explicitly designed for concurrent use
- Each `await session.post()` returns a distinct `ClientResponse` object
- Python async/await guarantees correct response routing
- No risk of response mixing between requests

**IMPORTANT**: Do NOT create sessions per-request - adds 10-50ms latency per request.

### 3. Streaming Detection

**Pattern**: Automatic detection based on response headers
```python
is_streaming = (
    response.content_type == "text/event-stream"
    or response.content_type == "application/x-ndjson"
    or response.headers.get("Transfer-Encoding") == "chunked"
    or "stream" in response.content_type.lower()
)
```

**Why**: Different APIs use different streaming conventions. Auto-detect to handle all.

### 4. Request Authentication

**Pattern**: Verify PKCS#1 signature from autoscaler
```python
def __check_signature(self, auth_data: AuthData) -> bool:
    if self.unsecured: return True
    # Verify signature of auth_data fields using fetched public key
```

**Why**: Prevent unauthorized requests to workers. Autoscaler signs all requests.

**Important**: Signature is over `{cost, endpoint, reqnum, request_idx, url}` sorted JSON.

### 5. Benchmark Functions

**Pattern**: User-provided async function measuring throughput
```python
async def benchmark(model_url: str, session: ClientSession) -> float:
    # Run performance tests
    # Return max_throughput in workload units per second
    return tokens_per_second  # or requests/sec, or custom metric
```

**Why**: Different APIs have different performance characteristics. User defines what "workload" means.

**Important**:
- Benchmark result is saved to `.has_benchmark` file (cached across restarts)
- Throughput reported to autoscaler for scaling decisions
- Must match the workload units used in `auth_data.cost`

### 6. Metrics Reporting

**Pattern**: Continuous background reporting to autoscaler
```python
while True:
    await sleep(1)
    if update_pending or elapsed > 10:
        await send_metrics_to_autoscaler()
        reset_metrics()
```

**Why**: Autoscaler needs real-time metrics for routing and scaling decisions.

**Important**:
- Send every 1s if updates pending
- Send at least every 10s even if idle
- Report `model_loading_time` exactly once when ready
- Include current workload for queue estimation

### 7. Error Handling

**Pattern**: Mark backend as errored and report continuously
```python
def backend_errored(self, msg: str):
    self.metrics._model_errored(msg)  # Sets error_msg in metrics
```

**Why**: Autoscaler needs to know worker is unhealthy to route traffic away.

**Important**:
- Errors reported in every metrics update
- `model_is_loaded=True` even on error (signals completion)
- Server enters "beacon mode" on fatal errors (continuously reports)

## Common Tasks

### Adding a New Benchmark

1. Create file in `benchmarks/my_api.py`
2. Implement async function:
   ```python
   async def benchmark(model_url: str, session: ClientSession) -> float:
       # Your benchmark logic
       return max_throughput
   ```
3. Set `BENCHMARK=benchmarks.my_api:benchmark`
4. Ensure benchmark workload units match what autoscaler sends in `auth_data.cost`

### Supporting a New HTTP Method

Already supported! The catch-all routes handle GET, POST, PUT, PATCH, DELETE.

### Changing Streaming Detection

Edit `__pass_through_response()` in `lib/backend.py`:
```python
is_streaming = (
    # Add your condition here
    response.headers.get("X-Stream") == "true"
)
```

### Adjusting Connection Pooling

Edit `session` property in `lib/backend.py`:
```python
connector = TCPConnector(
    limit=100,           # Max total connections
    limit_per_host=20,   # Max per host
    force_close=False,   # Enable connection reuse
)
```

## Important Gotchas

### 1. **Don't Create Sessions Per-Request**
- ❌ Creates latency (TCP + TLS handshake per request)
- ✅ Use shared session - it's safe for concurrent use

### 2. **Healthcheck Endpoint is Critical**
- Without it, startup uses fixed 10s delay (unreliable)
- Always provide `HEALTHCHECK_ENDPOINT` or ensure `/health` exists

### 3. **Benchmark Units Must Match Workload**
- If benchmark returns tokens/sec, autoscaler must send tokens in `auth_data.cost`
- Mismatch causes incorrect queue time calculations

### 4. **Force Close vs Connection Pooling**
- Current: `force_close=True` (closes after each request)
- Safer for long-running jobs but prevents connection reuse
- Consider `force_close=False` with proper limits for better performance

### 5. **Signature Verification Requires Public Key**
- Fetched from `REPORT_ADDR/pubkey` on startup
- Falls back to unsecured mode after 3 failed attempts
- Use `UNSECURED=true` for local development only

### 6. **Streaming Responses Must Not Be Buffered**
- Use `iter_any()` to stream chunks immediately
- Don't `await response.read()` on streaming responses

### 7. **Metrics Reset After Sending**
- Workload counters reset every metrics update
- Don't rely on cumulative values - they're windowed

### 8. **Request Rejection vs Cancellation**
- **Rejected**: Queue too long, never started (HTTP 429)
- **Cancelled**: Client disconnected mid-request (HTTP 499)
- Both need different metric tracking

## Testing Locally

### Without Autoscaler
```bash
export MODEL_SERVER_URL="http://localhost:8000"
export BENCHMARK="benchmarks.openai:benchmark"
export UNSECURED="true"  # Skip signature verification
python server.py
```

### Test Request (Passthrough Mode - RECOMMENDED)

When `UNSECURED=true`, you can send requests directly without wrapping in auth_data:

```bash
# Simple passthrough - just like calling your backend directly
curl -X POST http://localhost:3000/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "my-model",
    "prompt": "Hello",
    "max_tokens": 100
  }'
```

Vespa automatically creates minimal auth_data for metrics tracking.

### Test Request (Production Format)

You can also test with the full production format:

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

## File Structure

```
vespa/
├── server.py              # Entry point (configurable logging)
├── lib/
│   ├── backend.py         # Core proxy logic (~520 lines, refactored)
│   ├── metrics.py         # Metrics tracking (~305 lines, refactored)
│   ├── data_types.py      # Data structures (176 lines)
│   ├── server.py          # Server setup (61 lines)
│   └── test_utils.py      # Testing utilities
├── benchmarks/
│   ├── openai.py          # OpenAI-compatible benchmark
│   ├── tgi.py             # Text Generation Inference
│   └── comfyui.py         # ComfyUI benchmark
├── client.py              # Client-side proxy
├── utils/
│   ├── ssl.py             # SSL utilities
│   └── endpoint_util.py   # Endpoint helpers
├── examples/
│   ├── use_proxy.py       # Example: using as proxy
│   └── use_module.py      # Example: using as module
├── README.md              # User documentation
├── CLIENT.md              # Client usage docs
├── BENCHMARKS.md          # Benchmark writing guide
├── MIGRATION.md           # Migration from old architecture
├── STRUCTURE.md           # Detailed structure docs
├── CLAUDE.md              # This file - context for AI assistants
└── start_server.sh        # Production startup script
```

## Recent Changes Log

### 2025-12-03: Fixed MAX_WAIT_TIME Configuration and Benchmark Startup Pattern
- **Made MAX_WAIT_TIME configurable**: Changed `max_wait_time` field in `lib/backend.py:64-66` to read from environment variable (was previously hardcoded to 10.0)
- **Fixed benchmark startup pattern**: Removed unnecessary infinite sleep loop from `__run_benchmark_on_startup()` (`lib/backend.py:448-486`)
  - Benchmark now completes and exits cleanly instead of sleeping forever
  - Removed unused `BENCHMARK_SLEEP_INTERVAL` constant
- **Refactored `_start_tracking()`**: Changed from running benchmark in `gather()` with background tasks to sequential execution (`lib/backend.py:435-445`)
  - Now runs benchmark first to completion
  - Then starts infinite background loops (metrics, healthcheck, delete requests)
  - More logical flow: wait for backend ready → benchmark → start monitoring

**Impact**: Cleaner startup pattern that doesn't waste a coroutine sleeping indefinitely. MAX_WAIT_TIME now properly configurable as documented.

### 2025-12-03: Major Code Refactoring and Simplification
- **Logging Configuration**: Added `LOG_LEVEL` environment variable support (default: INFO) in `server.py:26-31`
- **Removed Deprecated Code**: Removed `distutils.util.strtobool` (deprecated), replaced with simple string comparison
- **Fixed Missing Import**: Added `Union` type import to `lib/data_types.py:5`
- **Extracted Magic Numbers**: Created constants at top of files for all magic numbers:
  - `lib/backend.py:30-37`: Added `HEALTHCHECK_RETRY_INTERVAL`, `HEALTHCHECK_POLL_INTERVAL`, `HEALTHCHECK_TIMEOUT`, `PUBKEY_FETCH_TIMEOUT`, `METRICS_RETRY_DELAY`
  - `lib/metrics.py:14-17`: Added `METRICS_UPDATE_INTERVAL`, `DELETE_REQUESTS_INTERVAL`, `METRICS_RETRY_DELAY`, `METRICS_MAX_RETRIES`
- **DRY TCPConnector**: Created `create_tcp_connector()` helper function (`lib/backend.py:41-46`) to eliminate duplicate connector configuration
- **Simplified HTTP Method Dispatch**: Replaced if/elif chain with dictionary-based dispatch (`lib/backend.py:280-291`)
- **Extracted Nested Functions**: Moved nested functions to proper methods for better organization:
  - `__verify_signature()` extracted from `__check_signature()` in `lib/backend.py:468-477`
  - `__post_delete_requests()` extracted from `__send_delete_requests_and_reset()` in `lib/metrics.py:160-185`
  - `__compute_autoscaler_data()` and `__send_data_to_autoscaler()` extracted from `__send_metrics_and_reset()` in `lib/metrics.py:221-280`
- **Broke Down Complex Handler**: Refactored 106-line `__handle_request()` into three focused methods:
  - `__parse_and_validate_request()`: Parse and validate request body (`lib/backend.py:115-126`)
  - `__wait_for_client_disconnect()`: Handle client disconnection (`lib/backend.py:128-133`)
  - `__forward_request_to_backend()`: Forward request and stream response (`lib/backend.py:135-168`)
  - Main handler now only 77 lines with clear flow (`lib/backend.py:170-246`)
- **Fixed Private Method Access**: Changed `__send_metrics_and_reset()` to `_send_metrics_and_reset()` to fix name-mangling issue in `lib/server.py:55`
- **Improved Code Documentation**: Added docstrings to all extracted methods explaining their purpose

**Impact**: Codebase is now significantly more readable, maintainable, and follows Python best practices. No functional changes - all refactoring is behavior-preserving.

### 2025-12-02: Passthrough Mode for Local Development
- Modified `__parse_request()` method in `lib/backend.py` (lines 213-261) to support passthrough mode
- When `UNSECURED=true`, requests can now be sent in two formats:
  1. **Passthrough (new)**: Send payload directly without auth_data wrapper (recommended for local testing)
  2. **Production format**: Include both auth_data and payload (for testing production flow)
- Passthrough mode automatically creates minimal AuthData for metrics tracking
- Updated CLAUDE.md and README.md with simpler local testing examples
- Makes local development much easier - just send requests as if Vespa were your backend API

### 2024-12-02: Health-Check-Based Startup
- Added `__wait_for_backend_ready()` method to poll healthcheck until ready
- Added `READY_TIMEOUT` environment variable (default: 1200s)
- Changed default healthcheck endpoint to `/health` if not specified
- Replaced hardcoded `sleep(5)` with proper health polling in benchmark startup
- Worker now fails gracefully if backend doesn't become ready within timeout
- Updated README.md to document new `READY_TIMEOUT` parameter

### Previous Architecture
- Originally had custom workers per API type (openai/, tgi/, comfyui/)
- Replaced with universal proxy architecture
- Reduced from 410+ lines per API to 80-240 lines total

---

## Maintenance Instructions for Claude

**CRITICAL**: When you make changes to this codebase, you MUST update this file immediately. Specifically:

1. **After adding/removing files**: Update "File Structure" section
2. **After modifying environment variables**: Update "Environment Variables" section
3. **After changing core logic**: Update relevant component description
4. **After fixing bugs or gotchas**: Document in "Important Gotchas"
5. **After significant changes**: Add entry to "Recent Changes Log" with date

**How to update**:
- Use the Edit tool to modify this file
- Keep descriptions concise but complete
- Include line numbers for key implementations
- Explain the "why" not just the "what"
- Date stamp entries in "Recent Changes Log"

This file is essential for maintaining context across conversations. Treat it as the single source of truth for understanding Vespa's architecture and implementation patterns.
