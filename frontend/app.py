"""
Flask chat frontend for the InMarket agent.

Serves a single-page chat UI and a POST /chat endpoint that hands the user's
question to the in-process LangGraph agent (agent.run_agent) and returns the
answer rendered to HTML, plus the tools the agent used.

Run from the project root (the MCP server must also be running):
    python -m frontend.app
Then open http://127.0.0.1:5000
"""
from __future__ import annotations

import os

import markdown as md
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from agent.agent import run_agent

load_dotenv()

app = Flask(__name__)

# Markdown -> HTML for rendering answers. The result is inserted into the page
# as HTML. The content comes from our own LLM (not arbitrary users), but
# sanitizing this output is an explicit item in the planned security pass
# (OWASP LLM02 / A03 — insecure output handling). TODO(security): sanitize.
_MD_EXTENSIONS = ["extra", "sane_lists"]


def _render_markdown(text: str) -> str:
    return md.markdown(text or "", extensions=_MD_EXTENSIONS)


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/chat")
def chat():
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "Please enter a question."}), 400

    try:
        result = run_agent(question)
    except Exception as exc:  # noqa: BLE001 — refined in the security pass
        # TODO(security): don't echo internal error detail to the client.
        return jsonify({"error": f"Agent error: {exc}"}), 500

    return jsonify(
        {
            "answer_html": _render_markdown(result["answer"]),
            "answer_md": result["answer"],
            "tool_calls": result.get("tool_calls", []),
        }
    )


def main() -> None:
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
