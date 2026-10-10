"""StockPilot AI - MCP Server.

Provides inventory and workshop assistance tools over Streamable HTTP transport.
"""

from pathlib import Path
import sys

# Ensure local imports work regardless of execution working directory
server_dir = Path(__file__).resolve().parent
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

# In official mcp SDK v2+, FastMCP was renamed to MCPServer
try:
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:
    from mcp.server.fastmcp import FastMCP

from storage import SqliteStorage

# Initialize storage and MCP server
storage = SqliteStorage()
mcp = FastMCP("StockPilot")


@mcp.tool()
def ping() -> str:
    """Return health check status for StockPilot."""
    return "StockPilot is alive"


@mcp.tool()
def check_stock(part: str) -> str:
    """Check current stock level and reorder threshold for a part name or SKU."""
    clean_part = part.strip()
    if not clean_part:
        return "Please specify a part name or SKU to check."

    # Check for exact match by SKU or exact name first
    exact_match = storage.get_part(clean_part)
    if exact_match:
        return f"You have {exact_match['qty']} {exact_match['name']}. Reorder level is {exact_match['reorder_level']}."

    # Perform partial case-insensitive search
    matches = storage.search_parts(clean_part)

    if not matches:
        return f"I couldn't find any parts matching '{clean_part}'."

    if len(matches) == 1:
        match = matches[0]
        return f"You have {match['qty']} {match['name']}. Reorder level is {match['reorder_level']}."

    # Multiple matches: ask user to clarify between options
    names = [m["name"] for m in matches]
    if len(names) == 2:
        return f"Did you mean {names[0]} or {names[1]}?"
    else:
        options = ", ".join(names[:-1]) + f", or {names[-1]}"
        return f"Did you mean {options}?"


if __name__ == "__main__":
    # Start server using Streamable HTTP transport on http://localhost:8000/mcp
    mcp.run(
        transport="streamable-http",
        host="127.0.0.1",
        port=8000,
        streamable_http_path="/mcp",
    )
