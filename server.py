"""
Vespa - Universal serverless proxy for Vast.ai

This server proxies requests to any backend API without custom transformation.
It handles authentication, metrics tracking, and benchmarking.

Environment variables:
- MODEL_SERVER_URL: URL of the backend server (e.g., http://localhost:8000)
- BENCHMARK: Python module path with benchmark function (e.g., benchmarks.openai:benchmark)
- HEALTHCHECK_ENDPOINT: Optional healthcheck endpoint (e.g., /health)
- ALLOW_PARALLEL: Whether to allow parallel requests (default: true)
- MAX_WAIT_TIME: Maximum queue wait time before rejecting (default: 10.0)

Usage:
    python server.py
"""
import os
import logging
import importlib
from typing import Optional, Callable, Awaitable
from aiohttp import web, ClientSession
from lib.backend import Backend
from lib.server import start_server

# Configure logging from environment variable
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s[%(levelname)-5s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__file__)


def load_benchmark_function() -> Optional[Callable[[str, ClientSession], Awaitable[float]]]:
    """
    Load benchmark function from BENCHMARK env var.

    Format: module.path:function_name
    Example: benchmarks.openai:benchmark

    The function should have signature:
        async def benchmark(model_url: str, session: ClientSession) -> float:
            # Run benchmark and return max_throughput in workload units per second
            return max_throughput
    """
    benchmark_spec = os.environ.get("BENCHMARK")

    if not benchmark_spec:
        log.warning("No BENCHMARK env var set, will use default throughput of 1.0")
        return None

    try:
        # Parse module:function
        if ":" not in benchmark_spec:
            raise ValueError(f"BENCHMARK must be in format 'module:function', got: {benchmark_spec}")

        module_path, function_name = benchmark_spec.rsplit(":", 1)

        log.debug(f"Loading benchmark function: {module_path}:{function_name}")
        module = importlib.import_module(module_path)
        benchmark_func = getattr(module, function_name)

        if not callable(benchmark_func):
            raise ValueError(f"Benchmark {benchmark_spec} is not callable")

        log.debug(f"Successfully loaded benchmark function: {benchmark_spec}")
        return benchmark_func

    except Exception as e:
        log.error(f"Failed to load benchmark function '{benchmark_spec}': {e}")
        log.warning("Will use default throughput of 1.0")
        return None


# Load configuration from environment
model_server_url = os.environ.get("MODEL_SERVER_URL", "http://localhost:8000")
healthcheck_endpoint = os.environ.get("HEALTHCHECK_ENDPOINT")
allow_parallel = os.environ.get("ALLOW_PARALLEL", "true").lower() == "true"
max_wait_time = float(os.environ.get("MAX_WAIT_TIME", "10.0"))

# Load benchmark function
benchmark_func = load_benchmark_function()

# Create backend
backend = Backend(
    model_server_url=model_server_url,
    benchmark_func=benchmark_func,
    healthcheck_endpoint=healthcheck_endpoint,
    allow_parallel_requests=allow_parallel,
    max_wait_time=max_wait_time,
)


async def handle_ping(_):
    """Simple ping endpoint for testing"""
    return web.Response(body="pong")


# Create catch-all route that forwards any path to the backend
# The actual endpoint is specified in auth_data.endpoint
routes = [
    # Catch-all route for all HTTP methods
    # The endpoint path comes from auth_data.endpoint in the request
    web.post("/{path:.*}", backend.create_handler()),
    web.get("/{path:.*}", backend.create_handler()),
    web.put("/{path:.*}", backend.create_handler()),
    web.patch("/{path:.*}", backend.create_handler()),
    web.delete("/{path:.*}", backend.create_handler()),
]

# Add ping endpoint for testing (doesn't require auth)
routes.append(web.get("/ping", handle_ping))

if __name__ == "__main__":
    log.info(f"Starting Vespa for backend: {model_server_url}")
    log.info(f"Healthcheck endpoint: {healthcheck_endpoint or 'None'}")
    log.info(f"Allow parallel requests: {allow_parallel}")
    log.info(f"Max wait time: {max_wait_time}s")
    log.info(f"Benchmark: {os.environ.get('BENCHMARK', 'None (will use default)')}")

    start_server(backend, routes)
