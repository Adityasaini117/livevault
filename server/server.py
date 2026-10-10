"""StockPilot AI - Minimal MCP Server.

Provides a ping health check tool over Streamable HTTP transport.
"""

# In official mcp SDK v2+, FastMCP was renamed to MCPServer
try:
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:
    from mcp.server.fastmcp import FastMCP

# Initialize the MCP server
mcp = FastMCP("StockPilot")


@mcp.tool()
def ping() -> str:
    """Return health check status for StockPilot."""
    return "StockPilot is alive"


if __name__ == "__main__":
    # Start server using Streamable HTTP transport on http://localhost:8000/mcp
    mcp.run(
        transport="streamable-http",
        host="127.0.0.1",
        port=8000,
        streamable_http_path="/mcp",
    )
