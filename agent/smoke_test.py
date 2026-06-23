"""
End-to-end smoke test for the agent.

Prerequisites:
  - The MCP server is running:  python -m mcp_server.server
  - ANTHROPIC_API_KEY and FRED_API_KEY are set in .env

Run from the project root:
  python -m agent.smoke_test
"""
from __future__ import annotations

from agent.agent import run_agent

QUESTIONS = [
    "What's the current U.S. unemployment rate?",
    "How has consumer sentiment changed over the past year?",
    "Compare unemployment and inflation since 2020.",
]


def main() -> None:
    for q in QUESTIONS:
        print("\n" + "=" * 70)
        print(f"Q: {q}")
        result = run_agent(q)
        tools = [t["name"] for t in result["tool_calls"]]
        print(f"Tools used: {tools}")
        print(f"A: {result['answer']}")


if __name__ == "__main__":
    main()
