"""
MCP tool loading.

Connects to the running FRED MCP server over Streamable HTTP and adapts its
tools into LangChain tools (via langchain-mcp-adapters) so the LangGraph agent
can call them. This is the only place that knows the MCP server's address.
"""
from __future__ import annotations

import os

from langchain_mcp_adapters.client import MultiServerMCPClient

# Where the FastMCP server (mcp_server/server.py) is listening.
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp/")


def _client() -> MultiServerMCPClient:
    return MultiServerMCPClient(
        {
            "fred": {
                "url": MCP_SERVER_URL,
                "transport": "streamable_http",
            }
        }
    )


async def load_mcp_tools():
    """Return the FRED MCP tools as a list of LangChain tools.

    Each returned tool opens its own short-lived session to the MCP server when
    invoked, so the list can be built once and reused across many requests.
    """
    return await _client().get_tools()
