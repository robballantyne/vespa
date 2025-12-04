"""
Benchmark function for OpenAI-compatible APIs (vLLM, Ollama, TGI, llama.cpp).

This benchmark measures throughput in tokens per second by sending concurrent
completion requests to the API.

Usage:
    VESPA_BENCHMARK=benchmarks.openai:benchmark

Environment variables:
    MODEL_NAME: Model name to use in requests (default: "model")
"""
import os
import time
import random
import logging
import asyncio
from aiohttp import ClientSession

try:
    import nltk
    nltk.download("words", quiet=True)
    WORD_LIST = nltk.corpus.words.words()
except Exception:
    # Fallback word list if nltk not available
    WORD_LIST = ["test", "benchmark", "performance", "throughput", "workload"] * 50

log = logging.getLogger(__name__)


def get_test_request() -> tuple[str, dict, float]:
    """
    Get a single test request for load testing.

    Returns:
        tuple: (endpoint_path, payload, workload)
            - endpoint_path: API endpoint (e.g., "/v1/completions")
            - payload: Request payload dict
            - workload: Workload cost (tokens)
    """
    model_name = os.environ.get("MODEL_NAME", "model")

    # Generate test prompt
    prompt = " ".join(random.choices(WORD_LIST, k=250))
    max_tokens = 500

    endpoint = "/v1/completions"
    payload = {
        "model": model_name,
        "prompt": prompt,
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }
    workload = max_tokens

    return endpoint, payload, workload


async def benchmark(backend_url: str, session: ClientSession, runs: int = 8) -> float:
    """
    Benchmark an OpenAI-compatible API.

    Args:
        backend_url: Base URL of the backend server
        session: aiohttp ClientSession for making requests
        runs: Number of benchmark runs (default: 8)

    Returns:
        max_throughput: Maximum workload processed per second
    """
    model_name = os.environ.get("MODEL_NAME", "model")
    endpoint = f"{backend_url}/v1/completions"

    log.info(f"Benchmarking OpenAI API at {endpoint}")

    # Generate test prompt
    system_prompt = """You are a helpful AI assistant. You have access to the following knowledge base:

    Zebras (US: /ˈziːbrəz/, UK: /ˈzɛbrəz, ˈziː-/)[2] (subgenus Hippotigris) are African equines
    with distinctive black-and-white striped coats. There are three living species: Grévy's zebra
    (Equus grevyi), the plains zebra (E. quagga), and the mountain zebra (E. zebra).

    Please answer the following question based on the above context."""

    # Initial warmup request
    log.info("Warming up...")
    warmup_prompt = " ".join(random.choices(WORD_LIST, k=50))
    warmup_payload = {
        "model": model_name,
        "prompt": f"{system_prompt}\n\n{warmup_prompt}",
        "max_tokens": 100,
        "temperature": 0.7,
    }

    try:
        async with session.post(endpoint, json=warmup_payload) as response:
            if response.status != 200:
                error_body = await response.text()
                log.error(
                    f"Warmup failed with status {response.status}\n"
                    f"Response: {error_body[:500]}"
                )
                return 1.0
            await response.read()  # Ensure response is fully consumed
    except Exception as e:
        log.error(
            f"Warmup failed with exception: {type(e).__name__}: {str(e)}\n"
            f"Exception details: {repr(e)}"
        )
        return 1.0

    # Run benchmark
    max_throughput = 0
    sum_throughput = 0
    concurrent_requests = 10  # OpenAI APIs usually support parallel

    for run in range(1, runs + 1):
        start = time.time()
        workloads = []

        # Create benchmark payloads
        async def run_single_request():
            prompt = " ".join(random.choices(WORD_LIST, k=250))
            payload = {
                "model": model_name,
                "prompt": f"{system_prompt}\n\n{prompt}",
                "max_tokens": 500,
                "temperature": 0.7,
            }
            workload = payload["max_tokens"]  # Workload is max_tokens

            try:
                async with session.post(endpoint, json=payload) as response:
                    if response.status == 200:
                        await response.read()  # Ensure response is fully consumed
                        return workload
                    else:
                        error_body = await response.text()
                        log.warning(
                            f"Request failed with status {response.status}\n"
                            f"Response: {error_body[:200]}"
                        )
                        return 0
            except Exception as e:
                log.warning(f"Request failed: {type(e).__name__}: {str(e)}")
                return 0

        # Run concurrent requests
        results = await asyncio.gather(*[run_single_request() for _ in range(concurrent_requests)])

        total_workload = sum(results)
        time_elapsed = time.time() - start
        successful = sum(1 for w in results if w > 0)

        if successful == 0:
            log.error(f"Benchmark run {run} failed: no successful responses")
            continue

        throughput = total_workload / time_elapsed
        sum_throughput += throughput
        max_throughput = max(max_throughput, throughput)

        log.info(
            f"Run {run}/{runs}: {successful}/{concurrent_requests} successful, "
            f"{total_workload} tokens in {time_elapsed:.2f}s = {throughput:.2f} tokens/s"
        )

    average_throughput = sum_throughput / runs if runs > 0 else 1.0
    log.info(
        f"Benchmark complete: avg={average_throughput:.2f} tokens/s, max={max_throughput:.2f} tokens/s"
    )

    return max_throughput if max_throughput > 0 else 1.0
