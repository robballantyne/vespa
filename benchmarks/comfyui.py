"""
Benchmark function for ComfyUI image generation API.

This benchmark measures throughput in workload units per second, where workload
is calculated based on image resolution and generation steps.

Usage:
    BENCHMARK=benchmarks.comfyui:benchmark

ComfyUI workload calculation:
    workload = (width * height * steps) / 1000 + resolution_adjustment
"""
import time
import random
import logging
import asyncio
from aiohttp import ClientSession

log = logging.getLogger(__name__)

# Test prompts for image generation
TEST_PROMPTS = [
    "a beautiful landscape with mountains and lakes",
    "a futuristic city at sunset",
    "a portrait of a wise old wizard",
    "a serene beach with palm trees",
    "a majestic castle on a hilltop",
    "a vibrant flower garden in spring",
    "a cozy cabin in the snowy woods",
]


def calculate_workload(width: int, height: int, steps: int) -> float:
    """
    Calculate ComfyUI workload based on resolution and steps.

    This matches the calculation from the old ComfyUI worker.
    """
    resolution = width * height

    # Resolution adjustments
    if resolution <= 512 * 512:
        resolution_adjustment = 0
    elif resolution <= 768 * 768:
        resolution_adjustment = 10
    elif resolution <= 1024 * 1024:
        resolution_adjustment = 20
    else:
        resolution_adjustment = 30

    # Step adjustments
    if steps <= 20:
        step_adjustment = 0
    elif steps <= 30:
        step_adjustment = 5
    else:
        step_adjustment = 10

    # Base workload calculation
    workload = (resolution * steps) / 1000.0 + resolution_adjustment + step_adjustment

    return workload


def get_test_request() -> tuple[str, dict, float]:
    """
    Get a single test request for load testing.

    Returns:
        tuple: (endpoint_path, payload, workload)
            - endpoint_path: API endpoint (e.g., "/runsync")
            - payload: Request payload dict
            - workload: Workload cost (resolution * steps / 1000)
    """
    # Standard test parameters
    width = 512
    height = 512
    steps = 20
    cfg = 7.0
    sampler_name = "euler_ancestral"
    scheduler = "normal"

    # Random prompt and seed
    prompt = random.choice(TEST_PROMPTS)
    seed = random.randint(1, 1000000)

    # Simple workflow for testing
    workflow = {
        "3": {
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler_name,
                "scheduler": scheduler,
                "denoise": 1,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0]
            },
            "class_type": "KSampler"
        },
        "4": {
            "inputs": {
                "ckpt_name": "model.safetensors"
            },
            "class_type": "CheckpointLoaderSimple"
        },
        "5": {
            "inputs": {
                "width": width,
                "height": height,
                "batch_size": 1
            },
            "class_type": "EmptyLatentImage"
        },
        "6": {
            "inputs": {
                "text": prompt,
                "clip": ["4", 1]
            },
            "class_type": "CLIPTextEncode"
        },
        "7": {
            "inputs": {
                "text": "nsfw, nude, text, watermark",
                "clip": ["4", 1]
            },
            "class_type": "CLIPTextEncode"
        },
        "8": {
            "inputs": {
                "samples": ["3", 0],
                "vae": ["4", 2]
            },
            "class_type": "VAEDecode"
        },
        "9": {
            "inputs": {
                "filename_prefix": "ComfyUI",
                "images": ["8", 0]
            },
            "class_type": "SaveImage"
        }
    }

    endpoint = "/runsync"
    payload = {
        "input": {
            "workflow_json": workflow
        }
    }
    workload = calculate_workload(width, height, steps)

    return endpoint, payload, workload


async def benchmark(backend_url: str, session: ClientSession, runs: int = 3) -> float:
    """
    Benchmark ComfyUI API.

    Args:
        backend_url: Base URL of the backend server (e.g., "http://localhost:8188")
        session: aiohttp ClientSession for making requests
        runs: Number of benchmark runs (default: 3, fewer because image gen is slow)

    Returns:
        max_throughput: Maximum workload units processed per second
    """
    # ComfyUI typically uses port 8188 and has /runsync endpoint for synchronous execution
    endpoint = f"{backend_url}/runsync"

    log.info(f"Benchmarking ComfyUI API at {endpoint}")

    # Standard benchmark parameters
    width = 512
    height = 512
    steps = 20
    cfg = 7.0
    sampler_name = "euler_ancestral"
    scheduler = "normal"

    # Calculate expected workload per request
    workload_per_request = calculate_workload(width, height, steps)
    log.info(f"Workload per request: {workload_per_request:.2f} units")

    # Simple workflow for benchmarking
    # This is a minimal text-to-image workflow
    def create_workflow(prompt: str, seed: int):
        return {
            "3": {
                "inputs": {
                    "seed": seed,
                    "steps": steps,
                    "cfg": cfg,
                    "sampler_name": sampler_name,
                    "scheduler": scheduler,
                    "denoise": 1,
                    "model": ["4", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0]
                },
                "class_type": "KSampler"
            },
            "4": {
                "inputs": {
                    "ckpt_name": "model.safetensors"
                },
                "class_type": "CheckpointLoaderSimple"
            },
            "5": {
                "inputs": {
                    "width": width,
                    "height": height,
                    "batch_size": 1
                },
                "class_type": "EmptyLatentImage"
            },
            "6": {
                "inputs": {
                    "text": prompt,
                    "clip": ["4", 1]
                },
                "class_type": "CLIPTextEncode"
            },
            "7": {
                "inputs": {
                    "text": "nsfw, nude, text, watermark",
                    "clip": ["4", 1]
                },
                "class_type": "CLIPTextEncode"
            },
            "8": {
                "inputs": {
                    "samples": ["3", 0],
                    "vae": ["4", 2]
                },
                "class_type": "VAEDecode"
            },
            "9": {
                "inputs": {
                    "filename_prefix": "ComfyUI",
                    "images": ["8", 0]
                },
                "class_type": "SaveImage"
            }
        }

    # Initial warmup request
    log.info("Warming up...")
    warmup_prompt = random.choice(TEST_PROMPTS)
    warmup_payload = {
        "workflow_json": create_workflow(warmup_prompt, random.randint(1, 1000000))
    }

    try:
        async with session.post(endpoint, json={"input": warmup_payload}, timeout=300) as response:
            if response.status != 200:
                log.error(f"Warmup failed with status {response.status}")
                # Try to read error message
                try:
                    error = await response.text()
                    log.error(f"Error: {error}")
                except:
                    pass
                return 1.0
            log.info("Warmup successful")
    except Exception as e:
        log.error(f"Warmup failed: {e}")
        return 1.0

    # Run benchmark
    # Note: ComfyUI typically can't handle parallel requests well, so we run sequentially
    max_throughput = 0
    sum_throughput = 0
    concurrent_requests = 1  # Sequential for ComfyUI

    for run in range(1, runs + 1):
        start = time.time()

        async def run_single_request():
            prompt = random.choice(TEST_PROMPTS)
            seed = random.randint(1, 1000000)
            payload = {
                "workflow_json": create_workflow(prompt, seed)
            }

            try:
                # ComfyUI can take a long time, set generous timeout
                async with session.post(endpoint, json={"input": payload}, timeout=300) as response:
                    if response.status == 200:
                        return workload_per_request
                    else:
                        log.warning(f"Request failed with status {response.status}")
                        return 0
            except Exception as e:
                log.warning(f"Request failed: {e}")
                return 0

        # Run requests (sequential for ComfyUI)
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
            f"{total_workload:.2f} workload in {time_elapsed:.2f}s = {throughput:.2f} workload/s"
        )

    average_throughput = sum_throughput / runs if runs > 0 else 1.0
    log.info(
        f"Benchmark complete: avg={average_throughput:.2f} workload/s, max={max_throughput:.2f} workload/s"
    )

    return max_throughput if max_throughput > 0 else 1.0
