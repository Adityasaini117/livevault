"""Unit tests for AWS Lambda handler and Mangum integration.

Tests:
1. Cold init with DynamoDB backend via moto (no real AWS required).
2. Fail-closed 401 response when LAMBDA_MODE=1 and LIFEVAULT_API_TOKEN is unset.
3. 401 response when token is missing or incorrect, verifying WWW-Authenticate: Bearer.
4. Case-insensitive Authorization header handling (e.g. authorization, Authorization, AUTHORIZATION).
5. 200 response for tools/list JSON-RPC request with valid Bearer token.
6. Warm invocation test: invoking the handler twice in one process returns 200 on both calls.
7. OAuth discovery endpoint returns 404 behind Mangum.
"""

import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

# Ensure server and deploy modules are discoverable
project_root = Path(__file__).resolve().parent.parent
server_dir = project_root / "server"
deploy_dir = project_root / "deploy"
for p in (str(server_dir), str(deploy_dir)):
    if p not in sys.path:
        sys.path.insert(0, p)

import boto3
from moto import mock_aws

import server
from storage_dynamodb import DynamoDbStorage
from lambda_handler import lambda_handler, create_asgi_app


def _make_function_url_event(
    path: str = "/mcp",
    method: str = "POST",
    headers: dict | None = None,
    body: dict | str | None = None,
) -> dict:
    """Helper to generate a Lambda Function URL format 2.0 event."""
    req_headers = {
        "host": "test-function-url.lambda-url.ap-southeast-2.on.aws",
        "content-type": "application/json",
        "accept": "application/json",
    }
    if headers:
        req_headers.update(headers)

    body_str = ""
    if isinstance(body, dict):
        body_str = json.dumps(body)
    elif isinstance(body, str):
        body_str = body

    return {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": path,
        "rawQueryString": "",
        "headers": req_headers,
        "requestContext": {
            "http": {
                "method": method,
                "path": path,
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
                "userAgent": "curl/8.0",
            }
        },
        "body": body_str,
        "isBase64Encoded": False,
    }


class LambdaContext:
    """Dummy Lambda context object."""
    def __init__(self):
        self.function_name = "lifevault-mcp"
        self.memory_limit_in_mb = "512"
        self.invoked_function_arn = "arn:aws:lambda:ap-southeast-2:123456789012:function:lifevault-mcp"
        self.aws_request_id = "test-request-id"


@mock_aws
class TestLambdaHandler(unittest.TestCase):
    def setUp(self):
        self.table_name = "lifevault-records"
        self.region = "ap-southeast-2"
        self.test_token = "secret-token-test-12345"

        # Mock environment variables
        self.env_patcher = patch.dict(
            os.environ,
            {
                "LAMBDA_MODE": "1",
                "STORAGE_BACKEND": "dynamodb",
                "DYNAMODB_TABLE": self.table_name,
                "AWS_DEFAULT_REGION": self.region,
                "AWS_REGION": self.region,
                "LIFEVAULT_API_TOKEN": self.test_token,
            },
        )
        self.env_patcher.start()

        # Set up mock DynamoDB table
        self.dynamodb = boto3.resource("dynamodb", region_name=self.region)
        self.table = self.dynamodb.create_table(
            TableName=self.table_name,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        self.table.wait_until_exists()

        # Point server.storage to DynamoDB storage backend
        self.orig_storage = server.storage
        server.storage = DynamoDbStorage(
            table_name=self.table_name,
            region_name=self.region,
            dynamodb_resource=self.dynamodb,
        )

    def tearDown(self):
        server.storage = self.orig_storage
        self.env_patcher.stop()

    def test_cold_init_with_dynamodb_backend(self):
        """Handler initializes cold without errors when DynamoDB backend is active."""
        ctx = LambdaContext()
        # Verify app creation
        app = create_asgi_app()
        self.assertIsNotNone(app)

        # Call with valid token
        event = _make_function_url_event(
            path="/mcp",
            headers={"authorization": f"Bearer {self.test_token}"},
            body={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        res = lambda_handler(event, ctx)
        self.assertEqual(res["statusCode"], 200)

    def test_fail_closed_when_token_unset_in_lambda_mode(self):
        """When LAMBDA_MODE=1 and LIFEVAULT_API_TOKEN is unset, reject all requests with 401."""
        os.environ["LIFEVAULT_API_TOKEN"] = ""

        ctx = LambdaContext()
        event = _make_function_url_event(
            path="/mcp",
            headers={"authorization": "Bearer any-token"},
            body={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )

        stderr_capture = io.StringIO()
        with patch("sys.stderr", stderr_capture):
            res = lambda_handler(event, ctx)

        self.assertEqual(res["statusCode"], 401)
        headers = {k.lower(): v for k, v in res.get("headers", {}).items()}
        self.assertEqual(headers.get("www-authenticate"), "Bearer")
        self.assertIn("LIFEVAULT_API_TOKEN is not set in LAMBDA_MODE", stderr_capture.getvalue())

    def test_401_without_token_or_invalid_token(self):
        """Requests without Authorization or with wrong token receive 401 with WWW-Authenticate: Bearer."""
        ctx = LambdaContext()

        # 1. No Authorization header
        event_no_auth = _make_function_url_event(
            path="/mcp",
            headers={},
            body={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        res_no_auth = lambda_handler(event_no_auth, ctx)
        self.assertEqual(res_no_auth["statusCode"], 401)
        headers_no_auth = {k.lower(): v for k, v in res_no_auth.get("headers", {}).items()}
        self.assertEqual(headers_no_auth.get("www-authenticate"), "Bearer")

        # 2. Wrong token
        event_wrong = _make_function_url_event(
            path="/mcp",
            headers={"authorization": "Bearer incorrect-token"},
            body={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        res_wrong = lambda_handler(event_wrong, ctx)
        self.assertEqual(res_wrong["statusCode"], 401)
        headers_wrong = {k.lower(): v for k, v in res_wrong.get("headers", {}).items()}
        self.assertEqual(headers_wrong.get("www-authenticate"), "Bearer")

    def test_case_insensitive_authorization_header(self):
        """Authorization header is recognized regardless of casing."""
        ctx = LambdaContext()
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}

        for header_name in ["authorization", "Authorization", "AUTHORIZATION"]:
            event = _make_function_url_event(
                path="/mcp",
                headers={header_name: f"Bearer {self.test_token}"},
                body=body,
            )
            res = lambda_handler(event, ctx)
            self.assertEqual(
                res["statusCode"],
                200,
                f"Failed with header case: {header_name}",
            )

    def test_200_tools_list_with_token(self):
        """Authorized tools/list request returns 200 with registered MCP tools list."""
        ctx = LambdaContext()
        event = _make_function_url_event(
            path="/mcp",
            headers={"authorization": f"Bearer {self.test_token}"},
            body={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        res = lambda_handler(event, ctx)
        self.assertEqual(res["statusCode"], 200)

        data = json.loads(res["body"])
        self.assertIn("result", data)
        tools = data["result"].get("tools", [])
        tool_names = [t["name"] for t in tools]

        # Verify key LifeVault tools are present
        self.assertIn("ping", tool_names)
        self.assertIn("add_record", tool_names)
        self.assertIn("find_record", tool_names)
        self.assertIn("upcoming_deadlines", tool_names)
        self.assertIn("spending_summary", tool_names)
        self.assertIn("renew_record", tool_names)
        self.assertIn("morning_brief", tool_names)
        self.assertIn("draft_warranty_claim", tool_names)
        self.assertIn("bill_anomalies", tool_names)

    def test_warm_invocations_both_return_200(self):
        """Invoking handler twice in the same process succeeds on both calls (warm execution path)."""
        ctx = LambdaContext()
        event = _make_function_url_event(
            path="/mcp",
            headers={"authorization": f"Bearer {self.test_token}"},
            body={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )

        res1 = lambda_handler(event, ctx)
        self.assertEqual(res1["statusCode"], 200)

        # Second invocation in the same Python process
        res2 = lambda_handler(event, ctx)
        self.assertEqual(res2["statusCode"], 200)

        data1 = json.loads(res1["body"])
        data2 = json.loads(res2["body"])
        self.assertEqual(len(data1["result"]["tools"]), len(data2["result"]["tools"]))

    def test_oauth_discovery_paths_return_404_behind_mangum(self):
        """OAuth discovery endpoints return 404 behind Mangum."""
        ctx = LambdaContext()
        event = _make_function_url_event(
            path="/.well-known/oauth-authorization-server",
            method="GET",
            headers={"authorization": f"Bearer {self.test_token}"},
        )
        res = lambda_handler(event, ctx)
        self.assertEqual(res["statusCode"], 404)
        self.assertIn("Not Found", res["body"])


if __name__ == "__main__":
    unittest.main()
