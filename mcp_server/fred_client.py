"""
FRED API client.

A thin async wrapper around the St. Louis Fed (FRED) REST API. This module
knows nothing about MCP or LLMs — it only handles HTTP, authentication, and
shaping FRED's raw JSON into clean Python dicts.

Keeping it separate from server.py preserves a clean separation of concerns:
the MCP/tool layer can change without touching API logic, and this client can
be unit-tested on its own. The only secret it needs is FRED_API_KEY.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

import httpx

FRED_BASE_URL = "https://api.stlouisfed.org/fred"

# FRED encodes a missing observation as the string ".".
FRED_MISSING_VALUE = "."


class FredAPIError(Exception):
    """Raised when the FRED API returns an error or cannot be reached."""


class FredClient:
    """Async client for the handful of FRED endpoints this project needs."""

    def __init__(self, api_key: Optional[str] = None, timeout: float = 30.0) -> None:
        self.api_key = api_key or os.getenv("FRED_API_KEY")
        if not self.api_key:
            raise FredAPIError(
                "FRED_API_KEY is not set. Add it to your .env file or environment."
            )
        self.timeout = timeout

    async def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        """Issue a GET to a FRED endpoint and return parsed JSON.

        The API key and file_type are injected here so callers never have to
        think about auth or response format.
        """
        query = {**params, "api_key": self.api_key, "file_type": "json"}
        url = f"{FRED_BASE_URL}/{endpoint}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, params=query)
        except httpx.RequestError as exc:
            raise FredAPIError(f"Could not reach FRED API: {exc}") from exc

        if resp.status_code != 200:
            # FRED returns a JSON body with `error_message` on 4xx errors.
            detail = resp.text
            try:
                detail = resp.json().get("error_message", detail)
            except Exception:
                pass
            raise FredAPIError(f"FRED API error {resp.status_code}: {detail}")

        return resp.json()

    async def get_series_info(self, series_id: str) -> dict[str, Any]:
        """Return metadata (title, units, frequency, …) for one series."""
        data = await self._get("series", {"series_id": series_id})
        seriess = data.get("seriess") or []
        if not seriess:
            raise FredAPIError(f"No FRED series found with id '{series_id}'.")
        s = seriess[0]
        return {
            "series_id": s.get("id"),
            "title": s.get("title"),
            "units": s.get("units"),
            "frequency": s.get("frequency"),
            "seasonal_adjustment": s.get("seasonal_adjustment"),
            "observation_start": s.get("observation_start"),
            "observation_end": s.get("observation_end"),
            "last_updated": s.get("last_updated"),
            "notes": s.get("notes"),
        }

    async def get_observations(
        self,
        series_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        sort_order: str = "asc",
        limit: Optional[int] = None,
        units: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Return a list of {date, value} observations for a series.

        Missing values ("." in FRED) are returned as None rather than dropped,
        so date alignment is preserved for comparisons.

        `units` applies a FRED-native transform to the values, e.g. "pc1"
        (percent change from a year ago / YoY) or "pch" (period-over-period
        percent change). Defaults to raw levels ("lin").
        """
        params: dict[str, Any] = {"series_id": series_id, "sort_order": sort_order}
        if start_date:
            params["observation_start"] = start_date
        if end_date:
            params["observation_end"] = end_date
        if limit:
            params["limit"] = limit
        if units:
            params["units"] = units

        data = await self._get("series/observations", params)
        observations: list[dict[str, Any]] = []
        for obs in data.get("observations", []):
            raw = obs.get("value")
            observations.append(
                {
                    "date": obs.get("date"),
                    "value": None if raw == FRED_MISSING_VALUE else _to_float(raw),
                }
            )
        return observations

    async def get_latest_changes(
        self, series_id: str, months_back: int = 12
    ) -> dict[str, Any]:
        """Latest observation plus its change over `months_back` months.

        Shared by the snapshot/pulse tools so the per-series fetch logic lives
        in one place. For the standard 12-month window it uses FRED's native
        transforms (`pc1` = YoY percent change, `ch1` = YoY absolute change);
        for any other window it computes the change from the raw observations
        (assumes a monthly series). Missing values ("." in FRED) surface as None.

        Returns: latest_value, latest_date, yoy_pct_change, yoy_change.
        """
        if months_back == 12:
            level, pct, chg = await asyncio.gather(
                self.get_observations(series_id, sort_order="desc", limit=1),
                self.get_observations(series_id, sort_order="desc", limit=1, units="pc1"),
                self.get_observations(series_id, sort_order="desc", limit=1, units="ch1"),
            )
            latest = level[0] if level else None
            return {
                "latest_value": latest["value"] if latest else None,
                "latest_date": latest["date"] if latest else None,
                "yoy_pct_change": pct[0]["value"] if pct else None,
                "yoy_change": chg[0]["value"] if chg else None,
            }

        # Custom window: compare the latest point to the one `months_back` back.
        window = await self.get_observations(
            series_id, sort_order="desc", limit=months_back + 1
        )
        latest = window[0] if window else None
        prior = window[months_back] if len(window) > months_back else None
        latest_v = latest["value"] if latest else None
        prior_v = prior["value"] if prior else None
        pct_change = abs_change = None
        if latest_v is not None and prior_v is not None:
            abs_change = round(latest_v - prior_v, 4)
            if prior_v != 0:
                pct_change = round((latest_v - prior_v) / prior_v * 100, 4)
        return {
            "latest_value": latest_v,
            "latest_date": latest["date"] if latest else None,
            "yoy_pct_change": pct_change,
            "yoy_change": abs_change,
        }

    async def search(self, keyword: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search FRED series by free-text keyword, ranked by popularity."""
        data = await self._get(
            "series/search",
            {
                "search_text": keyword,
                "limit": limit,
                "order_by": "popularity",
                "sort_order": "desc",
            },
        )
        results: list[dict[str, Any]] = []
        for s in data.get("seriess", []):
            results.append(
                {
                    "series_id": s.get("id"),
                    "title": s.get("title"),
                    "units": s.get("units"),
                    "frequency": s.get("frequency"),
                    "seasonal_adjustment": s.get("seasonal_adjustment_short"),
                    "popularity": s.get("popularity"),
                    "observation_start": s.get("observation_start"),
                    "observation_end": s.get("observation_end"),
                }
            )
        return results


def _to_float(value: Optional[str]) -> Optional[float]:
    """Best-effort float conversion; returns None for unparseable values."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
