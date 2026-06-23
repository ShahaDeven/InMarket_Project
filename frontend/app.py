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

import logging
import os
import time

import markdown as md
import nh3
from dotenv import load_dotenv
from flask import Flask, g, jsonify, render_template, request

from agent.agent import run_agent

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("inmarket")

app = Flask(__name__)

# A05 — security response headers applied to every response. The app loads only
# same-origin assets and emits no inline scripts/styles, so a strict CSP holds.
_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; base-uri 'self'; form-action 'self'; "
        "frame-ancestors 'none'; img-src 'self' data:; object-src 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


@app.before_request
def _start_timer() -> None:
    g._start = time.perf_counter()


@app.after_request
def _finalize(response):
    # A05 — security headers on every response.
    for header, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    # A09 — request logging (skip static assets to keep the log readable).
    if not request.path.startswith("/static"):
        elapsed = (time.perf_counter() - getattr(g, "_start", time.perf_counter())) * 1000
        logger.info(
            "%s %s -> %s (%.0f ms)",
            request.method, request.path, response.status_code, elapsed,
        )
    return response


# Markdown -> HTML, then allowlist-sanitized (OWASP LLM05 / A03 — improper
# output handling). The model's answer is rendered to HTML and injected into
# the page, so we strip everything outside a safe set of tags/attributes:
# no <script>/<img>, no event handlers, no javascript: URLs.
_MD_EXTENSIONS = ["extra", "sane_lists"]
_ALLOWED_TAGS = {
    "p", "br", "hr",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li",
    "strong", "em", "b", "i", "code", "pre",
    "blockquote",
    "a",
    "table", "thead", "tbody", "tr", "th", "td",
}
_ALLOWED_ATTRS = {"a": {"href", "title"}}


def _render_markdown(text: str) -> str:
    html = md.markdown(text or "", extensions=_MD_EXTENSIONS)
    return nh3.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer nofollow",
    )


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
    except Exception:  # noqa: BLE001
        # Log full detail server-side; return a generic message to the client
        # (OWASP LLM02 — sensitive information disclosure).
        logger.exception("Agent request failed")
        return (
            jsonify(
                {"error": "Sorry — something went wrong answering that. Please try again."}
            ),
            500,
        )

    tool_calls = result.get("tool_calls", [])
    # A09 — log question length (not content, for privacy) and tools used.
    logger.info(
        "chat ok: q_len=%d tools=%s",
        len(question), [t.get("name") for t in tool_calls],
    )
    return jsonify(
        {
            "answer_html": _render_markdown(result["answer"]),
            "answer_md": result["answer"],
            "tool_calls": tool_calls,
        }
    )


def main() -> None:
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
