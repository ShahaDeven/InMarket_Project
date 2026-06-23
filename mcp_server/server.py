"""
FastMCP server exposing the FRED API as MCP tools.

This is the *wrapper microservice*. It turns four well-described FRED
operations into MCP tools that any MCP-capable client (here, a LangGraph
agent) can call over HTTP. The HTTP/auth logic lives in fred_client.py; this
module only defines tool signatures, docstrings (which become the tool
descriptions the LLM reads), and response shaping.

Run locally from the project root:
    python -m mcp_server.server

It serves Streamable HTTP at  http://<MCP_HOST>:<MCP_PORT>/mcp/
(defaults: 0.0.0.0:8000).
"""
from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv
from fastmcp import FastMCP

from mcp_server.fred_client import FredAPIError, FredClient

# Load .env from the project root so FRED_API_KEY is available.
load_dotenv()

mcp = FastMCP("FRED Consumer Intelligence Server")

# One client per process. Constructed eagerly so a missing FRED_API_KEY
# fails fast at startup rather than on the first tool call.
fred = FredClient()


@mcp.tool
async def get_series_data(
    series_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    """Pull historical observations for a FRED economic data series.

    Use this to analyze a trend over time (e.g. inflation, unemployment,
    retail sales). Returns the series metadata plus a list of {date, value}
    points within the requested window.

    Args:
        series_id: FRED series ID, e.g. "CPIAUCSL" (CPI), "UNRATE"
            (unemployment rate), "RSXFS" (retail sales). Call search_series
            first if you do not know the ID.
        start_date: Optional ISO date "YYYY-MM-DD" lower bound. Omit for all history.
        end_date: Optional ISO date "YYYY-MM-DD" upper bound. Omit for latest.
    """
    try:
        info = await fred.get_series_info(series_id)
        observations = await fred.get_observations(series_id, start_date, end_date)
    except FredAPIError as exc:
        return {"error": str(exc)}
    return {
        "series": info,
        "start_date": start_date,
        "end_date": end_date,
        "count": len(observations),
        "observations": observations,
    }


@mcp.tool
async def get_latest_value(series_id: str) -> dict:
    """Get the single most recent observation for a FRED series.

    Use this for "what is X right now" questions. Returns the latest
    {date, value} plus series metadata (units, frequency).

    Args:
        series_id: FRED series ID, e.g. "UNRATE", "CPIAUCSL", "MORTGAGE30US".
    """
    try:
        info = await fred.get_series_info(series_id)
        observations = await fred.get_observations(series_id, sort_order="desc", limit=1)
    except FredAPIError as exc:
        return {"error": str(exc)}
    return {"series": info, "latest": observations[0] if observations else None}


@mcp.tool
async def search_series(keyword: str, limit: int = 10) -> dict:
    """Search FRED for data series matching a topic or keyword.

    Use this when the user names an economic concept but not a series ID
    (e.g. "consumer confidence", "gas prices", "median income"). Returns a
    ranked list of candidate series with their IDs and descriptions so you
    can pick the most relevant one to fetch.

    Args:
        keyword: Free-text topic, e.g. "consumer sentiment", "retail sales".
        limit: Max number of results to return (default 10).
    """
    try:
        results = await fred.search(keyword, limit=limit)
    except FredAPIError as exc:
        return {"error": str(exc)}
    return {"keyword": keyword, "count": len(results), "results": results}


@mcp.tool
async def compare_series(
    series_id_1: str,
    series_id_2: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    """Pull two FRED series over the same window for side-by-side comparison.

    Use this for relationships between two indicators (e.g. unemployment vs.
    inflation, wages vs. CPI). Returns metadata and observations for both
    series over the same window so you can compare trends.

    Args:
        series_id_1: First FRED series ID.
        series_id_2: Second FRED series ID.
        start_date: Optional ISO "YYYY-MM-DD" lower bound.
        end_date: Optional ISO "YYYY-MM-DD" upper bound.
    """

    async def _one(sid: str) -> dict:
        info = await fred.get_series_info(sid)
        obs = await fred.get_observations(sid, start_date, end_date)
        return {"series": info, "count": len(obs), "observations": obs}

    try:
        first = await _one(series_id_1)
        second = await _one(series_id_2)
    except FredAPIError as exc:
        return {"error": str(exc)}
    return {
        "start_date": start_date,
        "end_date": end_date,
        "series_1": first,
        "series_2": second,
    }


def main() -> None:
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8000"))
    mcp.run(transport="http", host=host, port=port)


if __name__ == "__main__":
    main()
