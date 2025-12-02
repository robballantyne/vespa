"""
Vespa Client - Simple proxy for Vast.ai serverless endpoints

This client abstracts away the Vast.ai routing complexity:
1. Automatically calls /route/ to get worker assignment
2. Wraps requests in auth_data + payload format
3. Forwards to worker and returns response

Usage as a proxy server:
    python client.py --endpoint my-endpoint --api-key YOUR_KEY

Usage as a module:
    from client import VastClient

    client = VastClient(endpoint_name="my-endpoint", api_key="YOUR_KEY")
    response = client.post("/v1/completions", json={"prompt": "test"})

Then just point your app at localhost:8010 instead of the real API!
"""
import argparse
import logging
import os
import sys
from typing import Optional, Dict, Any
import requests
from aiohttp import web
import asyncio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


class VastClient:
    """
    Simple client for Vast.ai serverless endpoints.

    Handles routing and authentication automatically.
    """

    def __init__(
        self,
        endpoint_name: str,
        api_key: str,
        autoscaler_url: str = "https://run.vast.ai",
        instance: str = "prod",
    ):
        """
        Initialize Vast.ai client.

        Args:
            endpoint_name: Name of your Vast.ai endpoint
            api_key: Endpoint API key (not your account API key!)
            autoscaler_url: Autoscaler URL (default: https://run.vast.ai)
            instance: Instance name (prod, alpha, candidate)
        """
        self.endpoint_name = endpoint_name
        self.api_key = api_key
        self.autoscaler_url = autoscaler_url.rstrip("/")
        self.instance = instance

        log.debug(f"Initialized VastClient for endpoint: {endpoint_name}")

    def route(self, endpoint: str, workload: float = 1.0) -> Optional[Dict[str, Any]]:
        """
        Call /route/ to get worker assignment.

        Args:
            endpoint: API endpoint path (e.g., /v1/completions)
            workload: Estimated workload units (default: 1.0)

        Returns:
            Dict with worker URL, signature, and routing info
        """
        try:
            response = requests.post(
                f"{self.autoscaler_url}/route/",
                json={
                    "endpoint": endpoint,
                    "cost": workload,
                },
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                },
                timeout=10,
            )

            if response.status_code != 200:
                log.error(f"Route failed: {response.status_code} - {response.text}")
                return None

            data = response.json()
            log.debug(f"Got worker assignment: {data.get('url', 'unknown')}")
            return data

        except Exception as e:
            log.error(f"Route error: {e}")
            return None

    def request(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[bytes] = None,
        headers: Optional[Dict[str, str]] = None,
        workload: Optional[float] = None,
        stream: bool = False,
    ) -> requests.Response:
        """
        Send request through Vast.ai routing.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: API path (e.g., /v1/completions)
            json: JSON payload (optional)
            data: Raw data payload (optional)
            headers: Additional headers (optional)
            workload: Estimated workload units (auto-detected from json if not provided)
            stream: Stream response (default: False)

        Returns:
            requests.Response object
        """
        # Auto-detect workload from common fields
        if workload is None and json:
            workload = (
                json.get("max_tokens", 0)
                or json.get("max_new_tokens", 0)
                or json.get("steps", 0)
                or 1.0
            )

        # Get worker assignment
        routing_info = self.route(path, workload or 1.0)
        if not routing_info:
            raise Exception("Failed to get worker assignment from autoscaler")

        # Construct request to worker
        worker_url = routing_info["url"]
        auth_data = {
            "cost": str(routing_info.get("cost", workload)),
            "endpoint": path,
            "reqnum": routing_info.get("reqnum", 0),
            "request_idx": routing_info.get("request_idx", 0),
            "signature": routing_info.get("signature", ""),
            "url": worker_url,
        }

        # Wrap payload
        payload = {
            "auth_data": auth_data,
            "payload": json or {},
        }

        # Forward to worker
        log.debug(f"{method} {worker_url}{path}")
        response = requests.request(
            method,
            worker_url,
            json=payload if json else None,
            data=data,
            headers=headers,
            timeout=300,  # Long timeout for model inference
            stream=stream,
        )

        return response

    def get(self, path: str, **kwargs) -> requests.Response:
        """GET request"""
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> requests.Response:
        """POST request"""
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs) -> requests.Response:
        """PUT request"""
        return self.request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs) -> requests.Response:
        """PATCH request"""
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs) -> requests.Response:
        """DELETE request"""
        return self.request("DELETE", path, **kwargs)


class VastProxy:
    """
    Local HTTP proxy server that forwards to Vast.ai endpoints.

    Start this proxy and point your app at localhost:8010 - all the
    Vast.ai routing complexity is handled automatically!
    """

    def __init__(
        self,
        endpoint_name: str,
        api_key: str,
        port: int = 8010,
        host: str = "127.0.0.1",
        autoscaler_url: str = "https://run.vast.ai",
    ):
        self.client = VastClient(endpoint_name, api_key, autoscaler_url)
        self.port = port
        self.host = host

    async def handle_request(self, request: web.Request) -> web.Response:
        """Forward incoming requests to Vast.ai"""
        path = request.path
        method = request.method

        log.info(f"{method} {path}")

        try:
            # Read request body
            if request.can_read_body:
                body_bytes = await request.read()
                try:
                    json_data = await request.json()
                except:
                    json_data = None
            else:
                body_bytes = None
                json_data = None

            # Forward through Vast.ai
            response = self.client.request(
                method=method,
                path=path,
                json=json_data,
                data=body_bytes if not json_data else None,
                headers=dict(request.headers),
            )

            # Return response
            return web.Response(
                body=response.content,
                status=response.status_code,
                headers=dict(response.headers),
            )

        except Exception as e:
            log.error(f"Request failed: {e}")
            return web.Response(
                status=500,
                text=f"Proxy error: {str(e)}",
            )

    async def start(self):
        """Start the proxy server"""
        app = web.Application()
        app.router.add_route("*", "/{path:.*}", self.handle_request)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()

        log.info(f"Vast.ai proxy started on http://{self.host}:{self.port}")
        log.info(f"Forwarding to endpoint: {self.client.endpoint_name}")
        log.info(f"Point your app at http://{self.host}:{self.port} instead of the real API")

        # Keep running
        try:
            while True:
                await asyncio.sleep(3600)
        except KeyboardInterrupt:
            log.info("Shutting down proxy...")
            await runner.cleanup()


def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Vast.ai Client Proxy - Forward requests to serverless endpoints"
    )
    parser.add_argument(
        "--endpoint",
        required=True,
        help="Vast.ai endpoint name"
    )
    parser.add_argument(
        "--api-key",
        help="Endpoint API key (or set VAST_API_KEY env var)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8010,
        help="Local proxy port (default: 8010)"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Local proxy host (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--autoscaler-url",
        default="https://run.vast.ai",
        help="Autoscaler URL (default: https://run.vast.ai)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    # Get API key from arg or env
    api_key = args.api_key or os.environ.get("VAST_API_KEY")
    if not api_key:
        log.error("ERROR: API key required! Use --api-key or set VAST_API_KEY env var")
        sys.exit(1)

    # Set log level
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Start proxy
    proxy = VastProxy(
        endpoint_name=args.endpoint,
        api_key=api_key,
        port=args.port,
        host=args.host,
        autoscaler_url=args.autoscaler_url,
    )

    asyncio.run(proxy.start())


if __name__ == "__main__":
    main()
