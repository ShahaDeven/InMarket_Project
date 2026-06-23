"""
Smoke test for the FRED MCP server.

Two modes:

  1. In-memory (no running server) — connects straight to the FastMCP object.
         python -m mcp_server.smoke_test

  2. Over HTTP (server must already be running in another terminal) — exercises
     the exact transport the LangGraph agent will use.
         python -m mcp_server.smoke_test http://127.0.0.1:8000/mcp/

Either way it lists the registered tools and calls two of them against the
real FRED API, so it also confirms your FRED_API_KEY works.
"""
from __future__ import annotations

import asyncio
import sys

from fastmcp import Client


def _unwrap(result):
    """Return the most useful payload across FastMCP client versions."""
    data = getattr(result, "data", None)
    if data is not None:
        return data
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured
    return getattr(result, "content", result)


async def run(target) -> None:
    async with Client(target) as client:
        tools = await client.list_tools()
        print("Registered tools:")
        for t in tools:
            print(f"  - {t.name}")
        print()

        print("get_latest_value('UNRATE'):")
        latest = await client.call_tool("get_latest_value", {"series_id": "UNRATE"})
        print(" ", _unwrap(latest))
        print()

        print("search_series('consumer sentiment', limit=3):")
        found = await client.call_tool(
            "search_series", {"keyword": "consumer sentiment", "limit": 3}
        )
        print(" ", _unwrap(found))
        print()

        print("get_category_snapshot('labor market', top_n=4):")
        snapshot = await client.call_tool(
            "get_category_snapshot", {"topic": "labor market", "top_n": 4}
        )
        print(" ", _unwrap(snapshot))


def main() -> None:
    if len(sys.argv) > 1:
        target = sys.argv[1]  # HTTP URL, e.g. http://127.0.0.1:8000/mcp/
    else:
        from mcp_server.server import mcp  # in-memory transport

        target = mcp
    asyncio.run(run(target))


if __name__ == "__main__":
    main()
