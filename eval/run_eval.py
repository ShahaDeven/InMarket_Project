"""
Small eval for the InMarket agent.

L1 (routing)   — did the agent call the right tool(s)/series?
L2 (grounding) — are the numbers it states actually correct? Ground truth is
                 resolved live by calling the MCP tools (which hit FRED), so
                 the suite never goes stale.

Prerequisites (same as the agent):
  - MCP server running:  python -m mcp_server.server
  - FRED_API_KEY and ANTHROPIC_API_KEY set in .env

Run from the project root:
  python -m eval.run_eval
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from dotenv import load_dotenv
from fastmcp import Client

from agent.agent import run_agent
from eval.cases import CASES
from mcp_server.server import mcp  # in-process tool access for ground truth

load_dotenv()

_NUM_RE = re.compile(r"[-+]?\d[\d,]*\.?\d*")


# ── ground truth (call the real tools in-process) ──────────────────────────
def _unwrap(result: Any) -> Any:
    for attr in ("data", "structured_content"):
        val = getattr(result, attr, None)
        if val is not None:
            return val
    return getattr(result, "content", result)


async def _call_tool(name: str, args: dict) -> Any:
    async with Client(mcp) as client:
        return _unwrap(await client.call_tool(name, args))


def _ground_truth(check: dict) -> dict:
    if check["type"] == "latest_value":
        sid = check["series_id"]
        res = asyncio.run(_call_tool("get_latest_value", {"series_id": sid})) or {}
        return {"series_id": sid, "value": (res.get("latest") or {}).get("value")}
    if check["type"] == "pulse":
        res = asyncio.run(_call_tool("get_demand_pulse", {})) or {}
        return {"pulse": (res.get("summary") or {}).get("pulse")}
    raise ValueError(f"unknown grounding check: {check['type']}")


# ── answer matching ────────────────────────────────────────────────────────
def _numbers(text: str) -> list[float]:
    out: list[float] = []
    for tok in _NUM_RE.findall(text):
        try:
            out.append(float(tok.replace(",", "")))
        except ValueError:
            pass
    return out


def _contains_number(text: str, value: float | None,
                     rel_tol: float = 0.01, abs_floor: float = 0.05) -> bool:
    if value is None:
        return False
    tol = max(abs_floor, abs(value) * rel_tol)
    return any(abs(n - value) <= tol for n in _numbers(text))


def _check_grounding(answer: str, check: dict) -> tuple[bool, str]:
    truth = _ground_truth(check)
    if check["type"] == "latest_value":
        sid, val = truth["series_id"], truth["value"]
        has_id = sid.lower() in answer.lower()
        has_val = _contains_number(answer, val)
        return has_id and has_val, f"{sid}={val} id:{_m(has_id)} val:{_m(has_val)}"
    label = (truth.get("pulse") or "")
    ok = bool(label) and label.lower() in answer.lower()
    return ok, f"pulse={label} {_m(ok)}"


def _m(ok: bool) -> str:
    return "OK" if ok else "X"


# ── runner ─────────────────────────────────────────────────────────────────
def _run_agent_retry(question: str, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            return run_agent(question)
        except Exception:  # mostly transient Anthropic 529s
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def main() -> None:
    rows = []
    for case in CASES:
        print(f"running: {case['name']} …")
        try:
            result = _run_agent_retry(case["question"])
        except Exception as exc:
            rows.append((case["name"], "ERROR", "ERROR", str(exc)[:50]))
            continue

        answer = result["answer"]
        actual = {tc.get("name") for tc in result.get("tool_calls", [])}

        required = case["required_tools"]
        l1_ok = required.issubset(actual)
        l1 = "PASS" if l1_ok else "FAIL"
        l1_detail = "" if l1_ok else f"want {sorted(required)}, got {sorted(actual)}"

        checks = case.get("grounding") or []
        if not checks:
            l2, l2_detail = "N/A", ""
        else:
            results = [_check_grounding(answer, c) for c in checks]
            l2 = "PASS" if all(ok for ok, _ in results) else "FAIL"
            l2_detail = "; ".join(d for _, d in results)

        rows.append((case["name"], l1, l2, (l1_detail + " " + l2_detail).strip()))

    # ── scorecard ──
    print("\n" + "=" * 84)
    print(f"{'CASE':<28}{'L1 ROUTING':<12}{'L2 GROUNDING':<14}DETAIL")
    print("-" * 84)
    for name, l1, l2, detail in rows:
        print(f"{name:<28}{l1:<12}{l2:<14}{detail}")
    print("=" * 84)

    l1_pass = sum(1 for _, l1, _, _ in rows if l1 == "PASS")
    l2_pass = sum(1 for _, _, l2, _ in rows if l2 == "PASS")
    l2_total = sum(1 for _, _, l2, _ in rows if l2 not in ("N/A", "ERROR"))
    print(f"L1 routing:   {l1_pass}/{len(rows)} passed")
    print(f"L2 grounding: {l2_pass}/{l2_total} passed (excludes N/A)")


if __name__ == "__main__":
    main()
