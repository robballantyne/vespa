# Migration Guide: Old Workers → Vespa

This guide shows how to migrate from the old worker-specific implementations to Vespa's new generic worker.

## Summary of Changes

### What Was Removed
- ✅ `workers/openai/` - 250+ lines
- ✅ `workers/tgi/` - 200+ lines
- ✅ `workers/comfyui/` - 400+ lines
- ✅ `workers/comfyui-json/` - 300+ lines
- ✅ `workers/hello_world/` - 150+ lines
- ✅ All `ApiPayload` classes
- ✅ All `EndpointHandler` classes
- ✅ All data transformation code
- ✅ Log file tailing

**Total removed:** ~1,300+ lines of boilerplate

### What Was Added
- ✅ `server.py` - 100 lines (works for ALL backends)
- ✅ `benchmarks/openai.py` - 130 lines
- ✅ `benchmarks/tgi.py` - 140 lines
- ✅ `benchmarks/comfyui.py` - 240 lines

**Total added:** ~610 lines (reusable across all backends)

**Structure:**
```
pyworker/
├── server.py        # Main entry point
├── lib/             # Core framework
└── benchmarks/      # Benchmark functions only
```

**Result:** 53% reduction in code, infinite increase in flexibility

---

## Migration by Backend

### OpenAI / vLLM / Ollama / llama.cpp

**Before:**
```bash
# Required custom worker directory: workers/openai/
# Required files: server.py, data_types/server.py
# Total: ~250 lines of custom code

export BACKEND="openai"
export BACKEND_URL="http://localhost:8000"
export MODEL_LOG="/path/to/model.log"
export HF_TOKEN="..."
```

**After:**
```bash
# No custom worker needed!
# Just 2 environment variables

export BACKEND_URL="http://localhost:8000"
export BENCHMARK="benchmarks.openai:benchmark"
export MODEL_NAME="meta-llama/Llama-2-7b-hf"  # Optional
```

**What Changed:**
- ❌ No more `BACKEND` variable needed (defaults to `generic`)
- ❌ No more `MODEL_LOG` required (no log tailing)
- ❌ No more custom worker code
- ✅ Simple `BENCHMARK` variable points to benchmark function
- ✅ Still works with vLLM, Ollama, TGI (OpenAI mode), llama.cpp

---

### Text Generation Inference (TGI)

**Before:**
```bash
# Required custom worker directory: workers/tgi/
# Required files: server.py, data_types.py
# Total: ~200 lines of custom code

export BACKEND="tgi"
export BACKEND_URL="http://localhost:8080"
export MODEL_LOG="/path/to/model.log"
export HF_TOKEN="..."
```

**After:**
```bash
# No custom worker needed!

export BACKEND_URL="http://localhost:8080"
export BENCHMARK="benchmarks.tgi:benchmark"
```

**What Changed:**
- ❌ No more `workers/tgi/` directory
- ❌ No more log tailing for startup detection
- ✅ Simple benchmark function replaces all custom code
- ✅ Supports TGI's native `/generate` endpoint

---

### ComfyUI

**Before:**
```bash
# Required custom worker directory: workers/comfyui/
# Required files: server.py, data_types/server.py, utils.py
# Total: ~400 lines of custom code

export BACKEND="comfyui"
export BACKEND_URL="http://localhost:8188"
export MODEL_LOG="/path/to/comfyui.log"
export COMFY_MODEL="model.safetensors"
```

**After:**
```bash
# No custom worker needed!

export BACKEND_URL="http://localhost:8188"
export BENCHMARK="benchmarks.comfyui:benchmark"
export ALLOW_PARALLEL="false"  # ComfyUI doesn't handle concurrency well
```

**What Changed:**
- ❌ No more `workers/comfyui/` directory
- ❌ No more `COMFY_MODEL` variable
- ❌ No more base64 image encoding in worker (handled by backend)
- ✅ Workload calculation preserved in benchmark
- ✅ Supports custom workflows via generic proxy

---

## API Compatibility

### Request Format

**No Change Required!** The request format is the same:

```json
{
  "auth_data": {
    "cost": "500",
    "endpoint": "/v1/completions",
    "reqnum": 1,
    "request_idx": 1,
    "signature": "...",
    "url": "..."
  },
  "payload": {
    "model": "my-model",
    "prompt": "test",
    "max_tokens": 100
  }
}
```

The generic worker:
1. Validates `auth_data` (same as before)
2. Forwards `payload` as-is to backend (no transformation!)
3. Streams response back (no transformation!)

### Response Format

**No Change Required!** Responses are passed through as-is:

```json
{
  "id": "cmpl-123",
  "object": "text_completion",
  "created": 1234567890,
  "model": "my-model",
  "choices": [...]
}
```

### Endpoints

**Now Flexible!** The old workers hardcoded specific endpoints:

**Before:**
```python
# Old openai/server.py
routes = [
    web.post("/v1/completions", ...),
    web.post("/v1/chat/completions", ...),
]
# Only these 2 endpoints worked!
```

**After:**
```python
# New generic/server.py
routes = [
    web.post("/{path:.*}", ...),
    web.get("/{path:.*}", ...),
    web.put("/{path:.*}", ...),
    # ALL paths work!
]
```

The endpoint is specified in `auth_data.endpoint` by the autoscaler.

---

## Workload Calculation

### Before: Manual Calculation in Worker

**Old openai worker:**
```python
class CompletionsData(ApiPayload):
    def count_workload(self) -> int:
        # Worker calculates workload from request
        return self.input.get("max_tokens", 0)
```

**Old comfyui worker:**
```python
class ComfyWorkflowData(ApiPayload):
    def count_workload(self) -> float:
        # Complex calculation in worker
        return (self.width * self.height * self.steps) / 1000 + adjustments
```

### After: Autoscaler Provides Workload

**New generic worker:**
```python
# Workload comes from autoscaler in auth_data.cost
workload = float(auth_data.cost)
```

The autoscaler calculates workload before routing the request. PyWorker just uses it for metrics tracking.

**Note:** Benchmark still calculates workload to measure throughput, but this doesn't affect request handling.

---

## Benchmarking

### Before: Built into Worker

**Old workers:**
- Benchmark code embedded in `EndpointHandler`
- `make_benchmark_payload()` method
- Hardcoded in worker implementation

### After: Standalone Function

**New approach:**
```python
# benchmarks/openai.py
async def benchmark(backend_url: str, session: ClientSession) -> float:
    # Run benchmark
    # Return max throughput
    return max_throughput
```

**Benefits:**
- ✅ Reusable across worker instances
- ✅ Easy to test independently
- ✅ Can be shared/imported
- ✅ Clear separation of concerns

---

## Environment Variables

### Required (Changed)

| Old | New | Notes |
|-----|-----|-------|
| `BACKEND` | - | Defaults to `generic`, no longer needed |
| `MODEL_LOG` | - | No log tailing, no longer needed |
| - | `BACKEND_URL` | Still required (was required before too) |
| - | `BENCHMARK` | New: points to benchmark function |

### Optional (New)

| Variable | Default | Description |
|----------|---------|-------------|
| `HEALTHCHECK_ENDPOINT` | None | Health check path (e.g., `/health`) |
| `ALLOW_PARALLEL` | `true` | Set to `false` for ComfyUI |
| `MAX_WAIT_TIME` | `10.0` | Queue timeout in seconds |

### Unchanged

| Variable | Description |
|----------|-------------|
| `MASTER_TOKEN` | Autoscaler auth token |
| `REPORT_ADDR` | Autoscaler URL |
| `CONTAINER_ID` | Instance ID |
| `PUBLIC_IPADDR` | Public IP |
| `WORKER_PORT` | Worker port (default: 3000) |
| `UNSECURED` | Disable auth (dev only) |

---

## Compatibility Matrix

| Backend | Old Worker | New Config | Status |
|---------|-----------|------------|--------|
| vLLM | `workers/openai` | `benchmarks.openai:benchmark` | ✅ Works |
| Ollama | `workers/openai` | `benchmarks.openai:benchmark` | ✅ Works |
| TGI | `workers/tgi` | `benchmarks.tgi:benchmark` | ✅ Works |
| TGI (OpenAI mode) | `workers/openai` | `benchmarks.openai:benchmark` | ✅ Works |
| llama.cpp | `workers/openai` | `benchmarks.openai:benchmark` | ✅ Works |
| ComfyUI | `workers/comfyui` | `benchmarks.comfyui:benchmark` | ✅ Works |
| Custom API | ❌ Required new worker | ✅ Just write benchmark | ✅ Easy! |

---

## Testing Your Migration

### 1. Backup Your Config

```bash
# Save your old environment variables
env | grep -E "BACKEND|MODEL_|COMFY_|HF_" > old_config.env
```

### 2. Update Config

```bash
# Clear old variables
unset BACKEND MODEL_LOG COMFY_MODEL

# Set new variables
export BACKEND_URL="http://localhost:8000"
export BENCHMARK="benchmarks.openai:benchmark"
```

### 3. Test Locally

```bash
# Enable debug mode
export UNSECURED="true"

# Start PyWorker
python -m workers.generic.server

# In another terminal, test the endpoint
curl -X POST http://localhost:3000/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "auth_data": {
      "cost": "100",
      "endpoint": "/v1/completions",
      "reqnum": 1,
      "request_idx": 1,
      "signature": "",
      "url": ""
    },
    "payload": {
      "model": "test",
      "prompt": "Hello",
      "max_tokens": 50
    }
  }'
```

### 4. Check Logs

Look for:
- ✅ "Benchmark complete: ... workload/s"
- ✅ "Starting request for reqnum:..."
- ✅ "Streaming response detected..." (for streaming)

### 5. Deploy to Vast.ai

Update your Vast.ai template with new environment variables:
```bash
BACKEND_URL=http://localhost:8000
BENCHMARK=benchmarks.openai:benchmark
```

---

## Rollback (If Needed)

If you need to rollback to old implementation:

```bash
# The old workers are deleted, so you'd need to:
git revert HEAD  # or git checkout <previous-commit>

# Restore old config
source old_config.env

# Restart
./start_server.sh
```

**Note:** This is a one-way migration. The old worker architecture is fundamentally different and can't coexist with the new flat structure.

---

## FAQ

### Q: Will this break existing deployments?

**A:** Not immediately. Existing workers will continue to work until you:
1. Update PyWorker to the new version
2. Change environment variables to use generic worker

### Q: Can I use custom endpoints?

**A:** Yes! The generic worker proxies ANY endpoint. Just specify it in `auth_data.endpoint`.

### Q: What if my API needs request transformation?

**A:** The generic worker passes requests through as-is. If you need transformation:
1. Transform on the client side before sending to PyWorker
2. Add a transformation layer between PyWorker and your backend
3. Write a custom worker (old style) if absolutely necessary

### Q: How do I add a new backend?

**A:** Just write a benchmark function! That's it.

```bash
# Create benchmark
cat > benchmarks/myapi.py << 'EOF'
async def benchmark(backend_url, session):
    # Your benchmark logic
    return max_throughput
EOF

# Use it
export BENCHMARK="benchmarks.myapi:benchmark"
```

### Q: What happened to workload calculation?

**A:** It moved to the autoscaler. The autoscaler now calculates workload before routing requests to workers. This is more efficient and allows for better routing decisions.

### Q: Can I still use custom metrics?

**A:** All metrics are preserved! PyWorker still tracks:
- Request counts
- Workload served/rejected/errored
- Queue depth
- Throughput

These are reported to the autoscaler exactly as before.

---

## Need Help?

- **Discord:** [https://discord.gg/Pa9M29FFye](https://discord.gg/Pa9M29FFye)
- **Reddit:** [https://reddit.com/r/vastai/](https://reddit.com/r/vastai/)
- **Issues:** [https://github.com/vast-ai/pyworker/issues](https://github.com/vast-ai/pyworker/issues)
