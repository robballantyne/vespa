"""
Vespa Client - Simple proxy for Vast.ai serverless endpoints

This client abstracts away the Vast.ai routing complexity:
1. Automatically calls /route/ to get worker assignment
2. Wraps requests in auth_data + payload format
3. Forwards to worker and returns response

Usage as a proxy server:
    python client.py --endpoint my-endpoint --api-key YOUR_KEY
    # Or with account key (auto-fetches endpoint key):
    python client.py --endpoint my-endpoint --account-key YOUR_ACCOUNT_KEY
    # Or interactive mode:
    python client.py

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
from pathlib import Path
from typing import Optional, Dict, Any, List
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
                if response.status_code == 401:
                    log.error("")
                    log.error("HINT: 401 Unauthorized usually means:")
                    log.error("  - You're using the wrong API key type")
                    log.error("  - Endpoint API key is required, not account API key")
                    log.error("  - Use --account-key to auto-fetch the correct key")
                    log.error("")
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
            raise Exception(
                "Failed to get worker assignment from autoscaler\n"
                "Possible causes:\n"
                "  - Wrong API key (are you using endpoint key, not account key?)\n"
                "  - Endpoint has no healthy workers\n"
                "  - Endpoint name is incorrect\n"
                "Check: https://console.vast.ai/endpoints"
            )

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

        # Handle GET/DELETE/HEAD differently (no body, use query params)
        if method in ["GET", "DELETE", "HEAD"]:
            # Encode auth_data as query parameters (prefixed with serverless_ to avoid conflicts)
            from urllib.parse import urlencode

            query_params = {
                "serverless_cost": auth_data["cost"],
                "serverless_endpoint": auth_data["endpoint"],
                "serverless_reqnum": str(auth_data["reqnum"]),
                "serverless_request_idx": str(auth_data["request_idx"]),
                "serverless_signature": auth_data["signature"],
                "serverless_url": auth_data["url"],
            }

            # Add payload fields as additional query params (unprefixed - these go to backend)
            if json:
                query_params.update(json)

            # Build full URL with query params
            full_url = f"{worker_url}{path}?{urlencode(query_params)}"

            log.debug(f"{method} {full_url}")
            response = requests.request(
                method,
                full_url,
                headers=headers,
                timeout=300,
                stream=stream,
            )
        else:
            # POST/PUT/PATCH: use JSON body
            payload = {
                "auth_data": auth_data,
                "payload": json or {},
            }

            full_url = f"{worker_url}{path}"
            log.debug(f"{method} {full_url}")
            response = requests.request(
                method,
                full_url,
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


def get_api_key_from_file() -> Optional[str]:
    """Read API key from ~/.vast_api_key file (vastai CLI compatible)"""
    try:
        key_file = Path.home() / ".vast_api_key"
        if key_file.exists():
            key = key_file.read_text().strip()
            if key:
                log.debug(f"Loaded API key from {key_file}")
                return key
    except Exception as e:
        log.debug(f"Could not read ~/.vast_api_key: {e}")
    return None


def fetch_endpoint_key(account_key: str, endpoint_name: str, instance: str = "prod") -> Optional[str]:
    """Fetch endpoint API key using account API key"""
    try:
        from utils.endpoint_util import Endpoint
        log.info(f"Fetching endpoint API key for '{endpoint_name}'...")
        endpoint_key = Endpoint.get_endpoint_api_key(endpoint_name, account_key, instance)
        if endpoint_key:
            log.info("Successfully retrieved endpoint API key")
            return endpoint_key
        else:
            log.error(f"Failed to fetch endpoint key for '{endpoint_name}'")
            log.error("Make sure the endpoint exists and you have access to it")
            return None
    except ImportError:
        log.error("ERROR: utils.endpoint_util not found. Cannot auto-fetch endpoint key.")
        log.error("Install with: pip install requests")
        return None
    except Exception as e:
        log.error(f"Error fetching endpoint key: {e}")
        return None


def list_endpoints(account_key: str, instance: str = "prod") -> List[str]:
    """List all available endpoints"""
    try:
        from utils.endpoint_util import Endpoint
        headers = {"Authorization": f"Bearer {account_key}"}
        url = f"{Endpoint.get_server_url(instance)}?autoscaler_instance={instance}"

        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            log.error(f"Failed to fetch endpoints: {response.status_code}")
            return []

        data = response.json()
        results = data.get("results", [])
        endpoints = [item.get("endpoint_name") for item in results if item.get("endpoint_name")]
        return sorted(endpoints)
    except Exception as e:
        log.error(f"Error listing endpoints: {e}")
        return []


def interactive_mode() -> tuple[str, str, int, str]:
    """Interactive mode - prompts for all required info"""
    print("\n" + "="*60)
    print("  Vespa Client - Interactive Setup")
    print("="*60 + "\n")

    # Get account key
    print("First, we need your Vast.ai account API key.")
    print("(Get it from: https://console.vast.ai/account)")
    print()
    account_key = input("Enter account API key: ").strip()

    if not account_key:
        print("\nERROR: Account API key is required")
        sys.exit(1)

    # List endpoints
    print("\nFetching your endpoints...")
    endpoints = list_endpoints(account_key)

    if not endpoints:
        print("\nNo endpoints found or failed to fetch.")
        print("Make sure you have created endpoints in console.vast.ai")
        sys.exit(1)

    # Show endpoints
    print(f"\nAvailable endpoints ({len(endpoints)}):")
    for i, ep in enumerate(endpoints, 1):
        print(f"  {i}. {ep}")
    print()

    # Select endpoint
    while True:
        try:
            choice = input(f"Select endpoint [1-{len(endpoints)}]: ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(endpoints):
                endpoint_name = endpoints[idx]
                break
            else:
                print(f"Please enter a number between 1 and {len(endpoints)}")
        except (ValueError, EOFError, KeyboardInterrupt):
            print("\nCancelled")
            sys.exit(0)

    # Get port
    print()
    port_input = input("Local proxy port [8010]: ").strip()
    port = int(port_input) if port_input else 8010

    # Fetch endpoint key
    print()
    endpoint_key = fetch_endpoint_key(account_key, endpoint_name)
    if not endpoint_key:
        sys.exit(1)

    print("\n" + "="*60)
    print(f"  Starting proxy for: {endpoint_name}")
    print(f"  Listening on: http://127.0.0.1:{port}")
    print("="*60 + "\n")

    return endpoint_name, endpoint_key, port, "https://run.vast.ai"


def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Vast.ai Client Proxy - Forward requests to serverless endpoints",
        epilog="""
Examples:
  # Interactive mode (easiest)
  python client.py

  # With endpoint API key
  python client.py --endpoint my-endpoint --api-key ENDPOINT_KEY

  # With account API key (auto-fetches endpoint key)
  python client.py --endpoint my-endpoint --account-key ACCOUNT_KEY

  # List available endpoints
  python client.py --list --account-key ACCOUNT_KEY

  # Use environment variables
  export VAST_ACCOUNT_KEY="your-account-key"
  export VAST_ENDPOINT="my-endpoint"
  python client.py

  # Or use ~/.vast_api_key file (vastai CLI compatible)
  echo "your-account-key" > ~/.vast_api_key
  python client.py --endpoint my-endpoint
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--endpoint",
        help="Vast.ai endpoint name (or set VAST_ENDPOINT env var)"
    )
    parser.add_argument(
        "--api-key",
        help="Endpoint API key (or set VAST_API_KEY env var)"
    )
    parser.add_argument(
        "--account-key",
        help="Account API key - will auto-fetch endpoint key (or set VAST_ACCOUNT_KEY env var, or use ~/.vast_api_key)"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available endpoints (requires account key)"
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
        "--instance",
        default="prod",
        choices=["prod", "alpha", "candidate"],
        help="Vast.ai instance (default: prod)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    # Set log level
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Priority: CLI flags > env vars > ~/.vast_api_key file
    account_key = (
        args.account_key
        or os.environ.get("VAST_ACCOUNT_KEY")
        or get_api_key_from_file()
    )

    endpoint_key = args.api_key or os.environ.get("VAST_API_KEY")
    endpoint_name = args.endpoint or os.environ.get("VAST_ENDPOINT")

    # Handle --list
    if args.list:
        if not account_key:
            log.error("ERROR: --list requires account key")
            log.error("Use: --account-key KEY or set VAST_ACCOUNT_KEY or create ~/.vast_api_key")
            sys.exit(1)

        log.info("Fetching endpoints...")
        endpoints = list_endpoints(account_key, args.instance)

        if not endpoints:
            log.error("No endpoints found")
            sys.exit(1)

        print(f"\nAvailable endpoints ({len(endpoints)}):")
        for ep in endpoints:
            print(f"  • {ep}")
        print()
        sys.exit(0)

    # Interactive mode if no endpoint specified
    if not endpoint_name:
        try:
            endpoint_name, endpoint_key, port, autoscaler_url = interactive_mode()
            args.port = port
            args.autoscaler_url = autoscaler_url
        except (KeyboardInterrupt, EOFError):
            print("\n\nCancelled")
            sys.exit(0)

    # Auto-fetch endpoint key if we have account key but no endpoint key
    if not endpoint_key and account_key:
        log.info("No endpoint API key provided, fetching using account key...")
        endpoint_key = fetch_endpoint_key(account_key, endpoint_name, args.instance)
        if not endpoint_key:
            sys.exit(1)

    # Validate we have everything needed
    if not endpoint_key:
        log.error("ERROR: Endpoint API key required!")
        log.error("")
        log.error("Options:")
        log.error("  1. Use --api-key with endpoint API key")
        log.error("  2. Use --account-key to auto-fetch endpoint key")
        log.error("  3. Set VAST_API_KEY or VAST_ACCOUNT_KEY env var")
        log.error("  4. Create ~/.vast_api_key with account key")
        log.error("  5. Run without arguments for interactive mode")
        log.error("")
        log.error("Get your account key from: https://console.vast.ai/account")
        sys.exit(1)

    # Start proxy
    log.info(f"Starting proxy for endpoint: {endpoint_name}")
    proxy = VastProxy(
        endpoint_name=endpoint_name,
        api_key=endpoint_key,
        port=args.port,
        host=args.host,
        autoscaler_url=args.autoscaler_url,
    )

    asyncio.run(proxy.start())


if __name__ == "__main__":
    main()
