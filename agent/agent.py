"""
The InMarket LangGraph agent.

A prebuilt ReAct agent (create_react_agent) wired to Claude Sonnet and the FRED
MCP tools. Exposes a single synchronous entry point, run_agent(), so the Flask
frontend can call it directly (in-process).

Async/sync bridge
-----------------
The agent and the MCP tools are async. Flask request handlers are synchronous.
Rather than spin up a fresh event loop per request (which breaks httpx /
Anthropic connection reuse and can raise "event loop is closed"), we run ONE
long-lived event loop on a background thread and dispatch coroutines onto it.
The agent is built once, lazily, on that loop and then reused.
"""
from __future__ import annotations

import asyncio
import os
import threading
from functools import lru_cache
from typing import Any

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent

from agent.mcp_client import load_mcp_tools
from agent.prompts import build_system_prompt

load_dotenv()

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "2048"))


class AgentRuntime:
    """Owns a single background event loop and the compiled agent."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="agent-loop", daemon=True
        )
        self._thread.start()
        self._agent: Any = None
        self._init_lock = threading.Lock()

    def _submit(self, coro):
        """Run a coroutine on the background loop and block for its result."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    async def _build_agent(self):
        tools = await load_mcp_tools()
        model = ChatAnthropic(model=MODEL, max_tokens=MAX_TOKENS, temperature=0)
        return create_react_agent(model, tools, prompt=build_system_prompt())

    def _ensure_agent(self):
        if self._agent is None:
            with self._init_lock:
                if self._agent is None:
                    self._agent = self._submit(self._build_agent())
        return self._agent

    async def _arun(self, question: str) -> dict[str, Any]:
        result = await self._agent.ainvoke(
            {"messages": [{"role": "user", "content": question}]}
        )
        messages = result["messages"]
        return {
            "answer": _as_text(messages[-1].content),
            "tool_calls": _extract_tool_calls(messages),
        }

    def ask(self, question: str) -> dict[str, Any]:
        self._ensure_agent()
        return self._submit(self._arun(question))


def _as_text(content: Any) -> str:
    """Anthropic content can be a string or a list of blocks; normalize to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", ""))
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content)


def _extract_tool_calls(messages) -> list[dict[str, Any]]:
    """Pull the tool calls the agent made, for transparency in the UI/logs."""
    calls = []
    for m in messages:
        for tc in getattr(m, "tool_calls", None) or []:
            calls.append({"name": tc.get("name"), "args": tc.get("args")})
    return calls


@lru_cache(maxsize=1)
def _runtime() -> AgentRuntime:
    return AgentRuntime()


def run_agent(question: str) -> dict[str, Any]:
    """Synchronous entry point for the frontend.

    Returns {"answer": str, "tool_calls": [{"name", "args"}, ...]}.
    """
    return _runtime().ask(question)
