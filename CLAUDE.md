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
  1. Parse `auth_data` and `payload` from request body (passthrough mode: if `VESPA_UNSECURED=true` and no auth_data, treat entire body as payload)
  2. Validate signature (unless `VESPA_UNSECURED=true`)
  3. Check queue wait time < `VESPA_MAX_WAIT_TIME`
  4. Acquire semaphore if `VESPA_ALLOW_PARALLEL=false`
  5. Forward request to backend
  6. Stream/pass response back to client
  7. Update metrics

**Important fields**:
- `backend_url`: Backend API base URL
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
- SSL support via `VESPA_USE_SSL` env var
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

### Required Variables
- `VESPA_BACKEND_URL`: Backend API base URL (e.g., `http://localhost:8000`)
- `VESPA_WORKER_PORT`: Port to listen on (required when running directly; `start_server.sh` sets default `3000`)

### Core Configuration
- `VESPA_BENCHMARK`: Python module path to benchmark (e.g., `benchmarks.openai:benchmark`) - defaults to 1.0 workload/sec
- `VESPA_HEALTHCHECK_ENDPOINT`: Health check path (optional; falls back to `/health`)
- `VESPA_ALLOW_PARALLEL`: Allow concurrent requests (default: `true`)
- `VESPA_MAX_WAIT_TIME`: Max queue wait time in seconds (default: `10.0`)
- `VESPA_READY_TIMEOUT`: Seconds to wait for backend ready (default: `1200`)
- `VESPA_UNSECURED`: Disable signature verification (default: `false`, **local dev only**)
- `VESPA_USE_SSL`: Enable SSL/TLS (default: `false` when running `server.py` directly, `true` when using `start_server.sh` on Vast.ai)
- `VESPA_LOG_LEVEL`: Logging level - DEBUG, INFO, WARNING, ERROR, CRITICAL (default: `INFO`)

### Advanced Tunables

**Connection Pooling:**
- `VESPA_CONNECTION_LIMIT`: Max total connections to backend (default: `100`)
- `VESPA_CONNECTION_LIMIT_PER_HOST`: Max connections per backend host (default: `20`)
- `VESPA_METRICS_CONNECTION_LIMIT`: Max total connections for metrics (default: `8`)
- `VESPA_METRICS_CONNECTION_LIMIT_PER_HOST`: Max connections per metrics host (default: `4`)

**Healthcheck:**
- `VESPA_HEALTHCHECK_RETRY_INTERVAL`: Seconds between healthcheck retries during startup (default: `5`)
- `VESPA_HEALTHCHECK_POLL_INTERVAL`: Seconds between periodic healthchecks (default: `10`)
- `VESPA_HEALTHCHECK_TIMEOUT`: Timeout for healthcheck requests in seconds (default: `10`)

**Metrics:**
- `VESPA_METRICS_UPDATE_INTERVAL`: Seconds between metrics updates to autoscaler (default: `1`)
- `VESPA_DELETE_REQUESTS_INTERVAL`: Seconds between delete request cleanup (default: `1`)
- `VESPA_METRICS_RETRY_DELAY`: Seconds between retry attempts (default: `2`)
- `VESPA_METRICS_MAX_RETRIES`: Max retry attempts for metrics reporting (default: `3`)
- `VESPA_METRICS_TIMEOUT`: Timeout for metrics HTTP requests in seconds (default: `10`)

**Security:**
- `VESPA_PUBKEY_TIMEOUT`: Timeout for fetching public key in seconds (default: `10`)
- `VESPA_PUBKEY_MAX_RETRIES`: Max attempts before falling back to unsecured mode (default: `3`)

**Other:**
- `VESPA_BENCHMARK_CACHE_FILE`: File path to cache benchmark results (default: `.has_benchmark`)

### Set by Vast.ai Platform
- `MASTER_TOKEN`: Authentication token for autoscaler
- `REPORT_ADDR`: Autoscaler URL for metrics reporting (comma-separated)
- `CONTAINER_ID`: Unique worker instance ID
- `PUBLIC_IPADDR`: Public IP address
- `VAST_TCP_PORT_{port}`: Mapped public port

### Backend-Specific (Not Vespa Config)
- `MODEL_NAME`: Used by vLLM, Ollama, TGI for model name in API requests
- `HF_TOKEN`: HuggingFace authentication token (used by model servers)

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
- Uses `VESPA_HEALTHCHECK_ENDPOINT` if set, otherwise defaults to `/health`
- Fails worker if no response within `VESPA_READY_TIMEOUT`
- Marks backend as errored and reports to autoscaler

### 2. Shared Session Safety

**Pattern**: Single `ClientSession` shared across all requests
```python
@cached_property
def session(self):
    connector = TCPConnector(force_close=True, enable_cleanup_closed=True)
    return ClientSession(self.backend_url, timeout=..., connector=connector)
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

**Important**:
- Signature is over `{cost, endpoint, reqnum, request_idx, url}` sorted JSON
- For POST/PUT/PATCH: auth_data + payload in JSON body
- For GET/DELETE/HEAD: auth_data in query parameters with `serverless_` prefix (no body allowed by HTTP spec)
  - `serverless_cost`, `serverless_endpoint`, `serverless_reqnum`, `serverless_request_idx`, `serverless_signature`, `serverless_url`
  - Unprefixed query params are passed through to backend as payload

### 5. Benchmark Functions

**Pattern**: User-provided async function measuring throughput
```python
async def benchmark(backend_url: str, session: ClientSession) -> float:
    # backend_url is for logging only
    # session already has base URL configured
    endpoint = "/v1/completions"  # Use relative path, NOT absolute URL

    async with session.post(endpoint, json=payload) as response:
        # Run performance tests

    return tokens_per_second  # or requests/sec, or custom metric
```

**Why**: Different APIs have different performance characteristics. User defines what "workload" means.

**Important**:
- **CRITICAL**: The `session` is created with `ClientSession(backend_url, ...)`, so you MUST pass relative paths (e.g., `/v1/completions`) to `session.post()`, NOT absolute URLs (e.g., `http://localhost:8000/v1/completions`). Passing absolute URLs will trigger an AssertionError in aiohttp.
- The `backend_url` parameter is provided for logging purposes only
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
   async def benchmark(backend_url: str, session: ClientSession) -> float:
       # Your benchmark logic
       return max_throughput
   ```
3. Set `VESPA_BENCHMARK=benchmarks.my_api:benchmark`
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
- Always provide `VESPA_HEALTHCHECK_ENDPOINT` or ensure `/health` exists

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
- Use `VESPA_UNSECURED=true` for local development only

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
export VESPA_BACKEND_URL="http://localhost:8000"
export VESPA_BENCHMARK="benchmarks.openai:benchmark"
export VESPA_UNSECURED="true"  # Skip signature verification
export VESPA_USE_SSL="false"   # Disable SSL for local testing (optional, false is default)
python server.py
```

**Note:** If using `start_server.sh` instead of running `server.py` directly, SSL defaults to `true`. Either set `VESPA_USE_SSL=false` or use HTTPS in your requests.

### Testing on Remote/Vast.ai Instance

When SSH'd into a Vast.ai worker where `start_server.sh` is running:

```bash
# Option 1: Use HTTPS (SSL is enabled by default in start_server.sh)
curl -k https://localhost:3000/v1/models

# Option 2: Disable SSL and restart
export VESPA_USE_SSL=false
# Restart the server, then use HTTP
curl http://localhost:3000/v1/models
```

### Test Request (Passthrough Mode - RECOMMENDED)

When `VESPA_UNSECURED=true`, you can send requests directly without wrapping in auth_data:

```bash
# If VESPA_USE_SSL=false (or running server.py directly):

# GET request (no body needed)
curl http://localhost:3000/v1/models

# POST request with JSON body
curl -X POST http://localhost:3000/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "my-model",
    "prompt": "Hello",
    "max_tokens": 100
  }'

# If VESPA_USE_SSL=true (default when using start_server.sh):

# GET request with HTTPS
curl -k https://localhost:3000/v1/models

# POST request with HTTPS
curl -k -X POST https://localhost:3000/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "my-model",
    "prompt": "Hello",
    "max_tokens": 100
  }'
```

Vespa automatically creates minimal auth_data for metrics tracking. GET/DELETE/HEAD requests don't require a body. The `-k` flag skips certificate verification for self-signed certs.

### GET Requests in Production Mode

For GET/DELETE/HEAD requests (which can't have JSON bodies), auth_data is passed via query parameters with `serverless_` prefix to avoid conflicts with backend parameters:

```bash
# Production GET request with auth_data in query params (serverless_ prefixed)
curl "https://worker-url:3000/v1/models?serverless_cost=1.0&serverless_endpoint=/v1/models&serverless_reqnum=1&serverless_request_idx=1&serverless_signature=BASE64_SIG&serverless_url=https://worker-url:3000"

# Can include backend query params too (unprefixed, passed through to backend)
curl "https://worker-url:3000/v1/models?serverless_cost=1.0&serverless_endpoint=/v1/models&serverless_reqnum=1&serverless_request_idx=1&serverless_signature=SIG&serverless_url=URL&limit=10&offset=0"

# In unsecured mode, query params (without serverless_ prefix) become payload for filtering/pagination
curl "http://localhost:3000/v1/models?limit=10&offset=0"
```

**Note:** The `serverless_` prefix ensures the serverless architecture's auth parameters don't conflict with your backend's query parameters.

### Test Request (Production Format)

You can also test POST requests with the full production format:

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
├── VESPA_BENCHMARKS.md          # Benchmark writing guide
├── MIGRATION.md           # Migration from old architecture
├── STRUCTURE.md           # Detailed structure docs
├── CLAUDE.md              # This file - context for AI assistants
└── start_server.sh        # Production startup script
```

## Recent Changes Log

### 2025-12-04: Implemented Query Parameter Auth for GET Requests (with serverless_ prefix)
- **New feature**: GET/DELETE/HEAD requests now support auth_data via query parameters with `serverless_` prefix
  - `lib/backend.py:118-192`: Complete rewrite of request parsing for bodiless HTTP methods
  - Parses auth_data from query params: `?serverless_cost=1.0&serverless_endpoint=/path&serverless_reqnum=1&serverless_request_idx=1&serverless_signature=xyz&serverless_url=http://...`
  - **Namespace protection**: `serverless_` prefix prevents conflicts with backend API query parameters
  - Validates signature for authenticated GET requests
  - Remaining query params (non-serverless_ fields) become payload for backend filtering/pagination
  - Falls back to minimal auth_data in unsecured mode if no auth params present
- **Updated client.py**: Added support for encoding auth_data as query params for GET/DELETE/HEAD requests
  - `client.py:172-220`: Split request handling into two branches based on HTTP method
  - GET/DELETE/HEAD: Encodes auth_data with `serverless_` prefix + payload unprefixed as query parameters
  - POST/PUT/PATCH: Wraps auth_data + payload in JSON body (existing behavior)
  - **Fixed bug**: Path wasn't being appended to worker_url (requests were going to wrong URL)
- **Solves production limitation**: Previously, GET requests were impossible in production mode since auth_data required JSON body

**Rationale**: In production mode with signature verification, all requests need auth_data. But GET/DELETE/HEAD requests can't have request bodies by HTTP spec. This created a fundamental limitation where these methods were unusable in production. Query parameter auth with `serverless_` prefix solves this by encoding auth_data in the URL while avoiding conflicts with backend query parameters. The prefix reflects that this is part of the Vast.ai serverless architecture, not Vespa-specific.

**Impact**: GET requests now work in both secured and unsecured modes. The autoscaler can route GET requests by including auth_data as query parameters. Backend APIs can use their own query parameters without conflicts.

**Example usage:**
```bash
# Production mode with auth_data in query params (serverless_ prefixed)
curl "https://worker:3000/v1/models?serverless_cost=1.0&serverless_endpoint=/v1/models&serverless_reqnum=1&serverless_request_idx=1&serverless_signature=SIG&serverless_url=URL"

# With backend query params (unprefixed, passed through)
curl "https://worker:3000/v1/models?serverless_cost=1.0&serverless_endpoint=/v1/models&serverless_reqnum=1&serverless_request_idx=1&serverless_signature=SIG&serverless_url=URL&limit=10&offset=0"

# Unsecured mode with query params as payload
curl "http://localhost:3000/v1/models?limit=10&offset=0"
```

### 2025-12-04: Fixed Documentation for VESPA_USE_SSL Default
- **Documentation fix**: Clarified that `VESPA_USE_SSL` has different defaults depending on how server is started
  - When running `python server.py` directly: defaults to `false` (`lib/server.py:18`)
  - When using `start_server.sh` (Vast.ai production): defaults to `true` (`start_server.sh:13`)
- **Updated documentation**: README.md and CLAUDE.md now correctly document both defaults
- **Impact**: Users on Vast.ai must use HTTPS (with `-k` flag for self-signed certs) or explicitly set `VESPA_USE_SSL=false`

**Rationale**: The code had two different default values depending on the entry point. `start_server.sh` sets SSL to true for production security, but the documentation only mentioned the direct server.py default of false. This caused confusion when "Empty reply from server" errors occurred due to HTTP/HTTPS protocol mismatch.

### 2025-12-04: Fixed GET Request Handling in Unsecured Mode
- **Fixed critical bug**: GET/DELETE/HEAD requests now work correctly in passthrough mode
  - `lib/backend.py:118-149`: Added special handling for requests without bodies
  - Previously tried to parse JSON body for all requests, causing 500 errors on GET requests
  - Now creates minimal auth_data with empty payload for bodiless requests in unsecured mode
  - Non-unsecured mode returns 400 error with helpful message
- **Error message**: Added clear error when GET requests attempted without VESPA_UNSECURED=true

**Rationale**: GET, DELETE, and HEAD requests don't have request bodies by HTTP spec, but the code was calling `await request.json()` for all requests. This caused uncaught exceptions when handling GET requests like `/v1/models`.

**Impact**: GET requests now work correctly in unsecured/passthrough mode. This is essential for model listing and health check endpoints.

### 2025-12-04: Fixed Benchmark Session Usage and Enhanced Error Handling
- **Fixed critical bug**: All benchmarks now use relative paths instead of absolute URLs
  - `benchmarks/openai.py:73`: Changed `endpoint = f"{backend_url}/v1/completions"` to `endpoint = "/v1/completions"`
  - `benchmarks/tgi.py:78`: Changed `endpoint = f"{backend_url}/generate"` to `endpoint = "/generate"`
  - `benchmarks/comfyui.py:173`: Changed `endpoint = f"{backend_url}/runsync"` to `endpoint = "/runsync"`
  - **Root cause**: Session is created with `ClientSession(backend_url, ...)`, so aiohttp expects relative paths
  - **Error**: Passing absolute URLs triggered `AssertionError: assert not url.is_absolute() and url.path.startswith("/")`
- **Improved error diagnostics**: All three benchmarks now provide detailed error information
  - Added full traceback logging to all benchmark error handlers
  - Non-200 responses: Now reads and logs response body (first 500 chars for warmup, 200 for requests)
  - Exceptions: Now logs exception type name, string message, repr, and full traceback
  - Proper response consumption: Added `await response.read()` to ensure proper connection cleanup
- **Fixed pubkey URL**: Added trailing `/` to pubkey fetch URL (`lib/backend.py:533`)
- **Documentation**: Updated benchmark pattern documentation to emphasize relative path requirement

**Rationale**: The benchmarks were constructing absolute URLs and passing them to a ClientSession that already had a base URL configured. This violated aiohttp's API contract and caused silent AssertionError failures. The enhanced error logging helped diagnose this issue.

**Impact**: Benchmarks now work correctly. This was a critical bug that prevented any benchmark from running. Enhanced error diagnostics made debugging possible on remote servers.

### 2025-12-03: Prefixed All Environment Variables with VESPA_ and Added Configurability
- **Environment Variable Naming**: All environment variables now use `VESPA_` prefix for clarity and namespace isolation
  - `BACKEND_URL` → `VESPA_BACKEND_URL`
  - `BENCHMARK` → `VESPA_BENCHMARK`
  - `HEALTHCHECK_ENDPOINT` → `VESPA_HEALTHCHECK_ENDPOINT`
  - `READY_TIMEOUT` → `VESPA_READY_TIMEOUT`
  - `ALLOW_PARALLEL` → `VESPA_ALLOW_PARALLEL`
  - `MAX_WAIT_TIME` → `VESPA_MAX_WAIT_TIME`
  - `WORKER_PORT` → `VESPA_WORKER_PORT`
  - `UNSECURED` → `VESPA_UNSECURED`
  - `USE_SSL` → `VESPA_USE_SSL`
  - `LOG_LEVEL` → `VESPA_LOG_LEVEL`
- **Made hardcoded constants configurable**: Added environment variable support for all configuration constants
  - `VESPA_BENCHMARK_CACHE_FILE` (default: ".has_benchmark")
  - `VESPA_PUBKEY_MAX_RETRIES` (default: 3)
  - `VESPA_HEALTHCHECK_RETRY_INTERVAL` (default: 5)
  - `VESPA_HEALTHCHECK_POLL_INTERVAL` (default: 10)
  - `VESPA_HEALTHCHECK_TIMEOUT` (default: 10)
  - `VESPA_PUBKEY_TIMEOUT` (default: 10)
  - `VESPA_METRICS_RETRY_DELAY` (default: 2)
  - `VESPA_METRICS_UPDATE_INTERVAL` (default: 1)
  - `VESPA_DELETE_REQUESTS_INTERVAL` (default: 1)
  - `VESPA_METRICS_MAX_RETRIES` (default: 3)
  - `VESPA_METRICS_TIMEOUT` (default: 10)
  - `VESPA_CONNECTION_LIMIT` (default: 100)
  - `VESPA_CONNECTION_LIMIT_PER_HOST` (default: 20)
  - `VESPA_METRICS_CONNECTION_LIMIT` (default: 8)
  - `VESPA_METRICS_CONNECTION_LIMIT_PER_HOST` (default: 4)
- **Updated all documentation**: README.md, CLAUDE.md, BENCHMARKS.md, STRUCTURE.md, MIGRATION.md, and start_server.sh all now use new naming
- **Variables NOT prefixed**:
  - Vast.ai-provided: `MASTER_TOKEN`, `REPORT_ADDR`, `CONTAINER_ID`, `PUBLIC_IPADDR`, `VAST_TCP_PORT_*` (set by platform)
  - Backend-specific: `MODEL_NAME`, `HF_TOKEN` (used by backend servers, not Vespa configuration)

**Rationale**: The `VESPA_` prefix provides clear namespace separation, preventing conflicts with user environment variables or other tools. Making all constants configurable allows for advanced tuning without code changes.

**Impact**: This is a breaking change for existing deployments. Users must update all environment variable names. All functionality remains identical.

### 2025-12-03: Refactored Load Testing to Use Benchmark Modules
- **Added `get_test_request()` function to all benchmarks**: Each benchmark now exports a helper function for load testing
  - `benchmarks/openai.py:31-56`: Returns (endpoint, payload, workload) for OpenAI API tests
  - `benchmarks/tgi.py:38-62`: Returns test request for TGI API
  - `benchmarks/comfyui.py:65-156`: Returns test request with full ComfyUI workflow
- **Completely refactored `lib/test_utils.py`**: Removed old `ApiPayload` abstraction
  - Now imports benchmark module dynamically via `-b` parameter
  - Calls `get_test_request()` from benchmark to get test payloads
  - Removed broken `ApiPayload` import (class was removed in earlier refactoring)
  - Simplified from 311 lines to 329 lines (cleaner, more focused)
- **Updated VESPA_BENCHMARKS.md**: Added comprehensive load testing documentation
  - New "Load Testing with Benchmarks" section with examples
  - Updated "Writing Custom Benchmarks" to include `get_test_request()` pattern

**Rationale**: The old approach required users to implement separate `ApiPayload.for_test()` methods, duplicating logic that already existed in benchmarks. This creates a single source of truth for test payloads, ensuring load tests use the same workload patterns as benchmarking.

**Impact**:
- Users no longer need to write custom `ApiPayload` classes for testing
- Load tests automatically use the same payloads as benchmarks
- Breaking change: Old load test command syntax changed - now requires `-b benchmark_module` parameter

**Usage**:
```bash
# Old (broken):
# python -m lib.test_utils -k KEY -e endpoint ...

# New:
python -m lib.test_utils -k KEY -e endpoint -b benchmarks.openai -n 100 -rps 10
```

### 2025-12-03: Renamed model_server_url to backend_url for Generic Naming
- **Renamed environment variable**: `MODEL_SERVER_URL` → `VESPA_BACKEND_URL` throughout codebase
- **Renamed field**: `model_server_url` → `backend_url` in `lib/backend.py:59`
- **Renamed parameter**: `model_url` → `backend_url` in benchmark function signatures
  - `benchmarks/openai.py:31`
  - `benchmarks/tgi.py:38`
  - `benchmarks/comfyui.py:65`
- **Updated documentation**: All references updated in README.md, VESPA_BENCHMARKS.md, STRUCTURE.md, MIGRATION.md, and CLAUDE.md
- **Updated scripts**: `start_server.sh` validation and logging now uses `VESPA_BACKEND_URL`

**Rationale**: The term "model server" implies AI models, but Vespa is designed as a universal proxy for any HTTP API backend. The new naming better reflects this generic purpose and avoids confusion when proxying non-AI services.

**Impact**: This is a breaking change for existing deployments. Users must update their environment variables from `MODEL_SERVER_URL` to `VESPA_BACKEND_URL`. All functionality remains identical.

### 2025-12-03: Fixed VESPA_MAX_WAIT_TIME Configuration and Benchmark Startup Pattern
- **Made VESPA_MAX_WAIT_TIME configurable**: Changed `max_wait_time` field in `lib/backend.py:64-66` to read from environment variable (was previously hardcoded to 10.0)
- **Fixed benchmark startup pattern**: Removed unnecessary infinite sleep loop from `__run_benchmark_on_startup()` (`lib/backend.py:448-486`)
  - Benchmark now completes and exits cleanly instead of sleeping forever
  - Removed unused `VESPA_BENCHMARK_SLEEP_INTERVAL` constant
- **Refactored `_start_tracking()`**: Changed from running benchmark in `gather()` with background tasks to sequential execution (`lib/backend.py:435-445`)
  - Now runs benchmark first to completion
  - Then starts infinite background loops (metrics, healthcheck, delete requests)
  - More logical flow: wait for backend ready → benchmark → start monitoring

**Impact**: Cleaner startup pattern that doesn't waste a coroutine sleeping indefinitely. VESPA_MAX_WAIT_TIME now properly configurable as documented.

### 2025-12-03: Major Code Refactoring and Simplification
- **Logging Configuration**: Added `VESPA_LOG_LEVEL` environment variable support (default: INFO) in `server.py:26-31`
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
- When `VESPA_UNSECURED=true`, requests can now be sent in two formats:
  1. **Passthrough (new)**: Send payload directly without auth_data wrapper (recommended for local testing)
  2. **Production format**: Include both auth_data and payload (for testing production flow)
- Passthrough mode automatically creates minimal AuthData for metrics tracking
- Updated CLAUDE.md and README.md with simpler local testing examples
- Makes local development much easier - just send requests as if Vespa were your backend API

### 2024-12-02: Health-Check-Based Startup
- Added `__wait_for_backend_ready()` method to poll healthcheck until ready
- Added `VESPA_READY_TIMEOUT` environment variable (default: 1200s)
- Changed default healthcheck endpoint to `/health` if not specified
- Replaced hardcoded `sleep(5)` with proper health polling in benchmark startup
- Worker now fails gracefully if backend doesn't become ready within timeout
- Updated README.md to document new `VESPA_READY_TIMEOUT` parameter

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
