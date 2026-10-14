"""AWS Lambda handler for LifeVault MCP Server behind Lambda Function URL.

Exposes the FastMCP Streamable HTTP ASGI application via Mangum.
In Lambda (LAMBDA_MODE=1):
- Runs FastMCP in stateless mode with JSON responses (stateless_http=True, json_response=True).
- Disables DNS rebinding protection only when LAMBDA_MODE=1 so Function URL domains
  (e.g. *.lambda-url.ap-southeast-2.on.aws) are accepted.
  Local behavior is unchanged (where DNS rebinding protection remains active for localhost).
  Bearer auth via ApiTokenAuthMiddleware remains the protection in Lambda mode.
- Lifespan is enabled (lifespan="on") so FastMCP's StreamableHTTPSessionManager starts.
- Creates a fresh ASGI app per invocation so that warm invocations never fail with
  'StreamableHTTPSessionManager.run() can only be called once per instance'.
"""

import os
from pathlib import Path
import sys
from typing import Any, Dict

# Ensure server module is discoverable from both local repo and packaged zip structures
current_dir = Path(__file__).resolve().parent
server_dir = current_dir.parent / "server"
if server_dir.exists() and str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

from mangum import Mangum
from mcp.server.transport_security import TransportSecuritySettings
import server


def create_asgi_app():
    """Create an ASGI app instance.
    
    When LAMBDA_MODE=1:
    - stateless_http=True: FastMCP operates statelessly across invocations.
    - json_response=True: Return standard JSON responses instead of SSE streams.
    - Disabling DNS rebinding protection must apply only when LAMBDA_MODE=1;
      local behavior is unchanged. Bearer auth via ApiTokenAuthMiddleware remains
      the protection.
    """
    if os.getenv("LAMBDA_MODE") == "1":
        # Disabling DNS rebinding protection applies only when LAMBDA_MODE=1;
        # local behavior unchanged. Bearer auth remains the protection.
        transport_sec = TransportSecuritySettings(enable_dns_rebinding_protection=False)
        return server.mcp.streamable_http_app(
            stateless_http=True,
            json_response=True,
            transport_security=transport_sec,
        )
    return server.mcp.streamable_http_app()


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """AWS Lambda entry point for Lambda Function URL invocations.
    
    FastMCP's StreamableHTTPSessionManager can only be run once per instance.
    Mangum with lifespan='on' enters and exits the lifespan context on each invocation.
    Therefore, caching the Mangum handler or ASGI app across invocations would cause
    subsequent warm invocations to crash with:
    'RuntimeError: StreamableHTTPSessionManager .run() can only be called once per instance'.
    We instantiate the ASGI app per invocation to guarantee isolation and reliability
    on warm execution paths.
    """
    app = create_asgi_app()
    handler = Mangum(app, lifespan="on")
    return handler(event, context)
