"""MCP client and tool dispatcher for Alexa+ Simulator.

Connects to an external MCP server over Streamable HTTP using the official
Python MCP SDK. Extracts tools, executes requested tool calls, and handles
unauthorized or connection failures with clear spoken messages.
"""

from typing import Any, Dict, List, Optional, Tuple
import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError


class MCPConnectionError(Exception):
    """Spoken-friendly exception for MCP connectivity or authorization issues."""
    pass


def _extract_nested_exception(exc: BaseException) -> Optional[BaseException]:
    """Traverse TaskGroup ExceptionGroups to find the underlying error."""
    if isinstance(exc, (httpx.HTTPStatusError, httpx.RequestError, MCPError)):
        return exc
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            target = _extract_nested_exception(sub)
            if target:
                return target
    return None


async def execute_mcp_tool_turn(
    server_url: str,
    bearer_token: Optional[str],
    tool_declarations_only: bool = False,
    tool_calls: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Execute an MCP transaction: fetch tools and/or invoke tools.

    Parameters:
        server_url: URL to the MCP Streamable HTTP endpoint.
        bearer_token: Optional token sent as Bearer authorization. Never logged.
        tool_declarations_only: If True, fetches and returns tool definitions only.
        tool_calls: List of dicts [{"name": str, "args": dict}] to execute.

    Returns:
        (tools_meta, execution_results)
    """
    clean_token = bearer_token.strip() if bearer_token and bearer_token.strip() else None

    # Configure default headers on the httpx client
    headers: Dict[str, str] = {}
    if clean_token:
        headers["Authorization"] = f"Bearer {clean_token}"

    execution_results: List[Dict[str, Any]] = []
    tools_meta: List[Dict[str, Any]] = []

    try:
        async with httpx.AsyncClient(headers=headers, timeout=20.0) as http_client:
            async with streamable_http_client(server_url, http_client=http_client) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    if tool_declarations_only:
                        listed = await session.list_tools()
                        for t in listed.tools:
                            tools_meta.append({
                                "name": t.name,
                                "description": t.description or "",
                                "input_schema": t.input_schema or {"type": "OBJECT", "properties": {}},
                            })
                        return tools_meta, execution_results

                    # Execute requested tool calls
                    if tool_calls:
                        for call in tool_calls:
                            c_name = call.get("name", "")
                            c_args = call.get("args", {}) or {}
                            res = await session.call_tool(c_name, c_args)

                            # Format text output
                            texts = []
                            if hasattr(res, "content") and res.content:
                                for part in res.content:
                                    if hasattr(part, "text"):
                                        texts.append(part.text)
                                    else:
                                        texts.append(str(part))
                            output_str = "\n".join(texts) if texts else str(res)
                            execution_results.append({
                                "name": c_name,
                                "args": c_args,
                                "result": output_str,
                            })

                    return tools_meta, execution_results

    except BaseException as e:
        underlying = _extract_nested_exception(e) or e

        # Check for 401 Unauthorized
        if isinstance(underlying, httpx.HTTPStatusError) and underlying.response.status_code == 401:
            if clean_token:
                raise MCPConnectionError("The LifeVault server rejected the access token. Check the token in settings.")
            else:
                raise MCPConnectionError("The LifeVault server requires an access token. Please provide one in settings.")

        # Check for MCPError carrying 401 or Unauthorized
        if isinstance(underlying, MCPError):
            err_msg = str(underlying).lower()
            if "unauthorized" in err_msg or "401" in err_msg:
                if clean_token:
                    raise MCPConnectionError("The LifeVault server rejected the access token. Check the token in settings.")
                else:
                    raise MCPConnectionError("The LifeVault server requires an access token. Please provide one in settings.")
            raise MCPConnectionError("The LifeVault server returned an error: " + str(underlying))

        # Check for connection problems
        if isinstance(underlying, (httpx.ConnectError, httpx.ConnectTimeout)):
            raise MCPConnectionError("I couldn't reach the LifeVault server. Make sure it is running and the URL is correct.")

        if isinstance(underlying, httpx.TimeoutException):
            raise MCPConnectionError("The LifeVault server took too long to respond.")

        # Check for HTTPStatusError other than 401
        if isinstance(underlying, httpx.HTTPStatusError):
            raise MCPConnectionError(f"The LifeVault server returned HTTP {underlying.response.status_code}.")

        raise MCPConnectionError("I encountered an issue connecting to the LifeVault server.")
