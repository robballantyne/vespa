import os
import json
import time
import base64
import importlib
import dataclasses
import logging
from asyncio import wait, sleep, gather, Semaphore, FIRST_COMPLETED, create_task
from typing import Tuple, Awaitable, NoReturn, Callable, Optional
from functools import cached_property
from distutils.util import strtobool

from aiohttp import web, ClientResponse, ClientSession, ClientConnectorError, ClientTimeout, TCPConnector
import asyncio

import requests
from Crypto.Signature import pkcs1_15
from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA

from lib.metrics import Metrics
from lib.data_types import (
    AuthData,
    JsonDataException,
    RequestMetrics,
)

VERSION = "0.3.0"

log = logging.getLogger(__file__)

BENCHMARK_INDICATOR_FILE = ".has_benchmark"
MAX_PUBKEY_FETCH_ATTEMPTS = 3


@dataclasses.dataclass
class Backend:
    """
    Simplified backend that acts as a pass-through proxy.

    This class is responsible for:
    1. Forwarding requests to the model server without transformation
    2. Tracking metrics and reporting to autoscaler
    3. Running benchmarks using a custom benchmark function
    """

    model_server_url: str
    benchmark_func: Optional[Callable[[str, ClientSession], Awaitable[float]]]
    healthcheck_endpoint: Optional[str] = None
    allow_parallel_requests: bool = True
    max_wait_time: float = 10.0
    ready_timeout: int = dataclasses.field(
        default_factory=lambda: int(os.environ.get("READY_TIMEOUT", "1200"))
    )
    reqnum = -1
    version = VERSION
    sem: Semaphore = dataclasses.field(default_factory=Semaphore)
    unsecured: bool = dataclasses.field(
        default_factory=lambda: bool(strtobool(os.environ.get("UNSECURED", "false"))),
    )
    report_addr: str = dataclasses.field(
        default_factory=lambda: os.environ.get("REPORT_ADDR", "https://run.vast.ai")
    )
    mtoken: str = dataclasses.field(
        default_factory=lambda: os.environ.get("MASTER_TOKEN", "")
    )

    def __post_init__(self):
        self.metrics = Metrics()
        self.metrics._set_version(self.version)
        self.metrics._set_mtoken(self.mtoken)
        self._total_pubkey_fetch_errors = 0
        self._pubkey = self._fetch_pubkey()
        self.__start_healthcheck: bool = False

    @property
    def pubkey(self) -> Optional[RSA.RsaKey]:
        if self._pubkey is None:
            self._pubkey = self._fetch_pubkey()
        return self._pubkey

    @cached_property
    def session(self):
        log.debug(f"starting session with {self.model_server_url}")
        connector = TCPConnector(
            force_close=True,  # Required for long running jobs
            enable_cleanup_closed=True,
        )

        timeout = ClientTimeout(total=None)
        return ClientSession(self.model_server_url, timeout=timeout, connector=connector)

    def create_handler(self, path: str = None):
        """
        Create a generic request handler that forwards any request to the backend.

        If path is provided, it will be used as the target endpoint.
        Otherwise, the path from auth_data.endpoint will be used.
        """
        async def handler_fn(request: web.Request) -> web.Response:
            return await self.__handle_request(request, path)

        return handler_fn

    async def __handle_request(
        self,
        request: web.Request,
        target_path: Optional[str] = None,
    ) -> web.Response:
        """Forward requests to the model endpoint as-is"""
        try:
            data = await request.json()
            auth_data, payload = self.__parse_request(data, request.path)
        except JsonDataException as e:
            return web.json_response(data=e.message, status=422)
        except json.JSONDecodeError:
            return web.json_response(dict(error="invalid JSON"), status=422)

        # Use cost from auth_data as workload (autoscaler calculates this)
        workload = float(auth_data.cost)
        request_metrics = RequestMetrics(
            request_idx=auth_data.request_idx,
            reqnum=auth_data.reqnum,
            workload=workload,
            status="Created"
        )

        async def cancel_api_call_if_disconnected() -> web.Response:
            await request.wait_for_disconnection()
            log.debug(f"request with reqnum: {request_metrics.reqnum} was canceled")
            self.metrics._request_canceled(request_metrics)
            raise asyncio.CancelledError

        async def make_request() -> web.Response:
            try:
                # Determine endpoint to use
                endpoint = target_path if target_path else auth_data.endpoint

                # Forward request to backend
                response = await self.__call_api(
                    endpoint=endpoint,
                    method=request.method,
                    payload=payload
                )

                status_code = response.status
                log.debug(
                    f"request with reqnum:{request_metrics.reqnum} "
                    f"returned status code: {status_code}"
                )

                # Pass through response
                res = await self.__pass_through_response(request, response)
                self.metrics._request_success(request_metrics)
                return res
            except requests.exceptions.RequestException as e:
                log.debug(f"[backend] Request error: {e}")
                self.metrics._request_errored(request_metrics)
                return web.Response(status=500)

        ###########

        if self.__check_signature(auth_data) is False:
            self.metrics._request_reject(request_metrics)
            return web.Response(status=401)

        if self.metrics.model_metrics.wait_time > self.max_wait_time:
            self.metrics._request_reject(request_metrics)
            return web.Response(status=429)

        acquired = False
        try:
            self.metrics._request_start(request_metrics)
            if self.allow_parallel_requests is False:
                log.debug(f"Waiting to acquire Sem for reqnum:{request_metrics.reqnum}")
                await self.sem.acquire()
                acquired = True
                log.debug(
                    f"Sem acquired for reqnum:{request_metrics.reqnum}, starting request..."
                )
            else:
                log.debug(f"Starting request for reqnum:{request_metrics.reqnum}")

            done, pending = await wait(
                [
                    create_task(make_request()),
                    create_task(cancel_api_call_if_disconnected()),
                ],
                return_when=FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

            done_task = done.pop()
            try:
                return done_task.result()
            except Exception as e:
                log.debug(f"Request task raised exception: {e}")
                return web.Response(status=500)
        except asyncio.CancelledError:
            # Client is gone. Do not write a response; just unwind.
            return web.Response(status=499)
        except Exception as e:
            log.debug(f"Exception in main handler loop {e}")
            return web.Response(status=500)
        finally:
            # Always release the semaphore if it was acquired
            if acquired:
                self.sem.release()
            self.metrics._request_end(request_metrics)

    def __parse_request(self, data: dict, request_path: str = "/") -> Tuple[AuthData, dict]:
        """Parse request JSON into auth_data and payload

        In production mode (unsecured=false):
            Requires both "auth_data" and "payload" fields

        In local dev mode (unsecured=true):
            Supports passthrough - if no "auth_data" field, treats entire request as payload
        """
        errors = {}
        auth_data = None
        payload = None

        # Passthrough mode: if unsecured and no auth_data, treat entire request as payload
        if self.unsecured and "auth_data" not in data:
            log.debug("Passthrough mode: treating entire request as payload")
            payload = data
            # Create minimal auth_data for metrics tracking
            auth_data = AuthData(
                cost="1.0",  # Default workload
                endpoint=request_path,
                reqnum=0,
                request_idx=0,
                signature="",
                url=""
            )
            return (auth_data, payload)

        # Standard mode: require both auth_data and payload
        try:
            if "auth_data" in data:
                auth_data = AuthData.from_json_msg(data["auth_data"])
            else:
                errors["auth_data"] = "field missing"
        except JsonDataException as e:
            errors["auth_data"] = e.message

        try:
            if "payload" in data:
                payload = data["payload"]
            else:
                errors["payload"] = "field missing"
        except Exception as e:
            errors["payload"] = str(e)

        if errors:
            raise JsonDataException(errors)

        return (auth_data, payload)

    async def __call_api(
        self, endpoint: str, method: str, payload: dict
    ) -> ClientResponse:
        """Call the backend API with the given method and payload"""
        url = endpoint
        log.debug(f"{method} to endpoint: '{url}', payload: {payload}")

        # Support all HTTP methods
        if method == "GET":
            return await self.session.get(url=url, params=payload if payload else None)
        elif method == "POST":
            return await self.session.post(url=url, json=payload)
        elif method == "PUT":
            return await self.session.put(url=url, json=payload)
        elif method == "PATCH":
            return await self.session.patch(url=url, json=payload)
        elif method == "DELETE":
            return await self.session.delete(url=url, json=payload)
        else:
            # Default to POST for unknown methods
            return await self.session.post(url=url, json=payload)

    async def __pass_through_response(
        self, client_request: web.Request, model_response: ClientResponse
    ) -> web.Response:
        """Pass through the model response to client without transformation"""

        if model_response.status != 200:
            # Pass through error responses directly
            content = await model_response.read()
            return web.Response(
                body=content,
                status=model_response.status,
                content_type=model_response.content_type
            )

        # Check if response is streaming
        is_streaming = (
            model_response.content_type == "text/event-stream"
            or model_response.content_type == "application/x-ndjson"
            or model_response.headers.get("Transfer-Encoding") == "chunked"
            or "stream" in model_response.content_type.lower()
        )

        if is_streaming:
            log.debug("Streaming response detected, proxying chunks...")
            response = web.StreamResponse()
            response.content_type = model_response.content_type

            # Copy relevant headers
            for header in ["Transfer-Encoding", "Cache-Control"]:
                if header in model_response.headers:
                    response.headers[header] = model_response.headers[header]

            await response.prepare(client_request)

            async for chunk in model_response.content.iter_any():
                await response.write(chunk)

            await response.write_eof()
            log.debug("Streaming complete")
            return response
        else:
            log.debug("Non-streaming response, proxying body...")
            content = await model_response.read()
            return web.Response(
                body=content,
                status=200,
                content_type=model_response.content_type
            )

    @cached_property
    def healthcheck_session(self):
        """Dedicated session for healthchecks to avoid conflicts with API session"""
        log.debug("creating dedicated healthcheck session")
        connector = TCPConnector(
            force_close=True,
            enable_cleanup_closed=True,
        )
        timeout = ClientTimeout(total=10)
        return ClientSession(timeout=timeout, connector=connector)

    async def __wait_for_backend_ready(self) -> None:
        """Poll healthcheck endpoint until backend is ready or timeout"""
        # Use configured endpoint or default to /health
        endpoint = self.healthcheck_endpoint if self.healthcheck_endpoint else "/health"
        url = f"{self.model_server_url}{endpoint}"

        log.info(f"Waiting for backend to be ready at {url} (timeout: {self.ready_timeout}s)")

        start_time = time.time()
        retry_interval = 5  # Poll every 5 seconds

        while True:
            elapsed = time.time() - start_time

            if elapsed >= self.ready_timeout:
                error_msg = f"Backend failed to become ready after {self.ready_timeout} seconds"
                log.error(error_msg)
                self.backend_errored(error_msg)
                raise RuntimeError(error_msg)

            try:
                async with self.healthcheck_session.get(url) as response:
                    if response.status == 200:
                        log.info(f"Backend is ready! (took {elapsed:.1f}s)")
                        return
                    else:
                        log.debug(f"Backend not ready yet (status {response.status}), retrying...")
            except Exception as e:
                log.debug(f"Backend not reachable yet: {e}, retrying...")

            await sleep(retry_interval)

    async def __healthcheck(self):
        """Periodic healthcheck of the backend"""
        if self.healthcheck_endpoint is None:
            log.debug("No healthcheck endpoint defined, skipping healthcheck")
            return

        while True:
            await sleep(10)
            if self.__start_healthcheck is False:
                continue
            try:
                log.debug(f"Performing healthcheck on {self.healthcheck_endpoint}")
                url = f"{self.model_server_url}{self.healthcheck_endpoint}"
                async with self.healthcheck_session.get(url) as response:
                    if response.status == 200:
                        log.debug("Healthcheck successful")
                    elif response.status == 503:
                        log.debug(f"Healthcheck failed with status: {response.status}")
                        self.backend_errored(
                            f"Healthcheck failed with status: {response.status}"
                        )
                    else:
                        log.debug(f"Healthcheck Endpoint not ready: {response.status}")
            except Exception as e:
                log.debug(f"Healthcheck failed with exception: {e}")
                self.backend_errored(str(e))

    async def _start_tracking(self) -> None:
        """Start background tasks for metrics and healthcheck"""
        await gather(
            self.__run_benchmark_on_startup(),
            self.metrics._send_metrics_loop(),
            self.__healthcheck(),
            self.metrics._send_delete_requests_loop()
        )

    def backend_errored(self, msg: str) -> None:
        """Mark backend as errored"""
        self.metrics._model_errored(msg)

    async def __run_benchmark_on_startup(self) -> NoReturn:
        """Run benchmark on startup to determine max throughput"""

        # Check if benchmark already completed
        try:
            with open(BENCHMARK_INDICATOR_FILE, "r") as f:
                max_throughput = float(f.readline())
                log.debug(f"Benchmark already completed: {max_throughput} workload/s")
                self.metrics._model_loaded(max_throughput=max_throughput)
                self.__start_healthcheck = True
                # Keep running to handle healthchecks
                while True:
                    await sleep(3600)
                return
        except FileNotFoundError:
            pass

        # Wait for backend to be ready via healthcheck
        await self.__wait_for_backend_ready()

        if self.benchmark_func is None:
            log.warning("No benchmark function provided, using default throughput of 1.0")
            max_throughput = 1.0
        else:
            try:
                log.debug("Running benchmark...")
                max_throughput = await self.benchmark_func(
                    self.model_server_url,
                    self.session
                )
                log.debug(f"Benchmark completed: {max_throughput} workload/s")
            except Exception as e:
                log.error(f"Benchmark failed: {e}")
                self.backend_errored(f"Benchmark failed: {e}")
                max_throughput = 1.0

        # Save benchmark result
        with open(BENCHMARK_INDICATOR_FILE, "w") as f:
            f.write(str(max_throughput))

        self.metrics._model_loaded(max_throughput=max_throughput)
        self.__start_healthcheck = True

        # Keep running
        while True:
            await sleep(3600)

    def __check_signature(self, auth_data: AuthData) -> bool:
        """Verify request signature from autoscaler"""
        if self.unsecured is True:
            return True

        def verify_signature(message, signature):
            try:
                key = RSA.import_key(self.pubkey)
                h = SHA256.new(message.encode())
                pkcs1_15.new(key).verify(h, base64.b64decode(signature))
                return True
            except Exception as e:
                log.debug(f"Signature verification failed: {e}")
                return False

        auth_data_dict = {
            "cost": auth_data.cost,
            "endpoint": auth_data.endpoint,
            "reqnum": auth_data.reqnum,
            "request_idx": auth_data.request_idx,
            "url": auth_data.url,
        }

        message = json.dumps(auth_data_dict, sort_keys=True)
        return verify_signature(message, auth_data.signature)

    def _fetch_pubkey(self) -> Optional[RSA.RsaKey]:
        """Fetch public key from autoscaler"""
        if self.unsecured:
            log.debug("Running in unsecured mode, skipping pubkey fetch")
            return None

        try:
            response = requests.get(
                f"{self.report_addr}/pubkey",
                timeout=10
            )
            response.raise_for_status()
            pubkey_str = response.text
            log.debug(f"Fetched pubkey: {pubkey_str[:50]}...")
            return RSA.import_key(pubkey_str)
        except Exception as e:
            self._total_pubkey_fetch_errors += 1
            log.debug(f"Failed to fetch pubkey (attempt {self._total_pubkey_fetch_errors}): {e}")

            if self._total_pubkey_fetch_errors >= MAX_PUBKEY_FETCH_ATTEMPTS:
                log.error("Max pubkey fetch attempts reached, running in unsecured mode")
                self.unsecured = True

            return None
