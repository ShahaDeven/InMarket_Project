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

import asyncio
import os
from typing import Any, Optional

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


@mcp.tool
async def get_category_snapshot(topic: str, top_n: int = 6) -> dict:
    """Build a multi-indicator "state of X" snapshot for an economic topic.

    Use this for broad overview questions like "how's the labor market?",
    "give me a housing snapshot", or "state of inflation". It finds the most
    popular FRED series for the topic and, for each, returns the latest value
    plus the year-over-year percent change (FRED-native `pc1` transform) — so
    you can narrate a whole sector in one call instead of fetching series
    one by one.

    Args:
        topic: An economic area or sector, e.g. "labor market", "housing",
            "inflation", "consumer spending".
        top_n: How many top series to include (default 6).

    Returns a dict with the topic, an `as_of` date, and a `series` list where
    each item has: series_id, title, units, frequency, latest_value,
    latest_date, yoy_pct_change (% change from a year ago — best for index
    series like CPI), and yoy_change (absolute change from a year ago — this is
    percentage points for rate series like unemployment). Either may be None
    if unavailable.
    """

    async def _series_snapshot(s: dict[str, Any]) -> dict[str, Any]:
        sid = s.get("series_id")
        try:
            changes = await fred.get_latest_changes(sid)
        except FredAPIError as exc:
            # Keep one failing series from sinking the whole snapshot.
            return {"series_id": sid, "title": s.get("title"), "error": str(exc)}
        return {
            "series_id": sid,
            "title": s.get("title"),
            "units": s.get("units"),
            "frequency": s.get("frequency"),
            **changes,  # latest_value, latest_date, yoy_pct_change, yoy_change
        }

    try:
        series_list = await fred.search(topic, limit=top_n)
    except FredAPIError as exc:
        return {"error": str(exc)}
    if not series_list:
        return {"topic": topic, "count": 0, "series": [], "note": "No matching series found."}

    snapshots = await asyncio.gather(*[_series_snapshot(s) for s in series_list])
    as_of = max(
        (s["latest_date"] for s in snapshots if s.get("latest_date")), default=None
    )
    return {"topic": topic, "as_of": as_of, "count": len(snapshots), "series": snapshots}


# Curated demand-pulse series with polarity. CPI is context-only (not scored).
_DEMAND_PULSE_SERIES = [
    {"series_id": "UMCSENT", "title": "Consumer Sentiment", "polarity": "positive"},
    {"series_id": "RRSFS", "title": "Real Retail & Food Services Sales", "polarity": "positive"},
    {"series_id": "DSPIC96", "title": "Real Disposable Personal Income", "polarity": "positive"},
    {"series_id": "UNRATE", "title": "Unemployment Rate", "polarity": "negative"},
    {"series_id": "CPIAUCSL", "title": "CPI (All Urban Consumers)", "polarity": "context"},
]
# Deadband: |YoY %| below this counts as "flat" rather than a directional signal.
_DEMAND_FLAT_BAND = 0.5


def _demand_signal(yoy_pct: Optional[float], polarity: str) -> Optional[str]:
    """Classify a YoY change as improving/deteriorating/flat, adjusted for
    polarity (e.g. a rising UNRATE is deteriorating). Context series are not
    scored. Pure arithmetic — no interpretation.
    """
    if polarity == "context":
        return "context"
    if yoy_pct is None:
        return None
    effective = yoy_pct if polarity == "positive" else -yoy_pct
    if effective > _DEMAND_FLAT_BAND:
        return "improving"
    if effective < -_DEMAND_FLAT_BAND:
        return "deteriorating"
    return "flat"


@mcp.tool
async def get_demand_pulse(months_back: int = 12) -> dict:
    """Composite read on whether U.S. consumer demand is strengthening or weakening.

    Use this for questions about consumer demand, consumer mood, or "is now a
    good time to ...". It fetches a fixed, curated set of demand indicators and
    tags each with a directional signal, plus an overall pulse label. This tool
    only fetches and classifies data with simple arithmetic — it does NOT
    interpret; the plain-English narrative is your job.

    Args:
        months_back: YoY comparison window in months (default 12). 12 uses
            FRED's native year-over-year transform.

    Returns:
        - `series`: one entry per indicator with series_id, title, latest_value,
          date, yoy_pct, polarity, and signal in {improving, deteriorating,
          flat} (CPI is "context", not scored).
        - `summary`: counts of improving vs deteriorating signals and an overall
          `pulse` label (strengthening / softening / mixed) derived purely from
          those counts.
    """
    months_back = max(1, min(months_back, 120))

    async def _one(cfg: dict[str, str]) -> dict[str, Any]:
        sid = cfg["series_id"]
        try:
            changes = await fred.get_latest_changes(sid, months_back=months_back)
        except FredAPIError as exc:
            return {
                "series_id": sid, "title": cfg["title"],
                "polarity": cfg["polarity"], "error": str(exc),
            }
        yoy = changes["yoy_pct_change"]
        return {
            "series_id": sid,
            "title": cfg["title"],
            "latest_value": changes["latest_value"],
            "date": changes["latest_date"],
            "yoy_pct": yoy,
            "polarity": cfg["polarity"],
            "signal": _demand_signal(yoy, cfg["polarity"]),
        }

    series = await asyncio.gather(*[_one(c) for c in _DEMAND_PULSE_SERIES])

    improving = sum(1 for s in series if s.get("signal") == "improving")
    deteriorating = sum(1 for s in series if s.get("signal") == "deteriorating")
    flat = sum(1 for s in series if s.get("signal") == "flat")
    if improving > deteriorating:
        pulse = "strengthening"
    elif deteriorating > improving:
        pulse = "softening"
    else:
        pulse = "mixed"

    return {
        "months_back": months_back,
        "as_of": max((s["date"] for s in series if s.get("date")), default=None),
        "series": series,
        "summary": {
            "improving": improving,
            "deteriorating": deteriorating,
            "flat": flat,
            "pulse": pulse,
        },
    }


def main() -> None:
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8000"))
    mcp.run(transport="http", host=host, port=port)


if __name__ == "__main__":
    main()
