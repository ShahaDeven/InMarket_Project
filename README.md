# InMarket — Consumer & Economic Intelligence Agent

An **agentic web application** that answers natural-language questions about the
U.S. economy and consumer trends using **live [FRED](https://fred.stlouisfed.org/)
data**. A Flask chat UI talks to a **LangGraph** agent (Claude Sonnet) that calls
tools exposed by a **FastMCP** server wrapping the FRED REST API.

> _"How's the labor market doing?" · "Are wages keeping up with inflation?" ·
> "Give me a snapshot of the housing market."_

The agent decides which tools to call, pulls the right FRED series, and
synthesizes a grounded answer — citing the series IDs, units, and dates it used.

---

## Architecture

Three layers, deployed as **two containers** (one shared image):

```
   ┌─────────────────────────────────────────────────────────────┐
   │  Browser  ──►  Flask chat UI ───────────────────────────┐   │
   │                      │  POST /chat                      │   │
   │                      ▼                                  │   │
   │            LangGraph ReAct agent  (Claude Sonnet)       │   │  web container
   │                      │  (in-process)                    │   │  (only :5000 exposed)
   │                      │  langchain-mcp-adapters          │   │
   └──────────────────────┼──────────────────────────────────────┘
                          │  Streamable HTTP  (internal network)
   ┌──────────────────────▼───────────────────────────────────────┐
   │            FastMCP server  →  6 FRED tools                   │  mcp_server container
   │                      │                                       │  (not published)
   └──────────────────────┼───────────────────────────────────────┘
                          │  HTTPS REST
                          ▼
                  FRED API (St. Louis Fed)
```

**Separation of concerns:**

| Layer | Folder | Responsibility |
|-------|--------|----------------|
| MCP server | [`mcp_server/`](mcp_server/) | Wraps the FRED REST API as MCP tools. `fred_client.py` = pure HTTP/data logic; `server.py` = tool definitions. Knows nothing about LLMs. |
| Agent | [`agent/`](agent/) | LangGraph ReAct agent + system prompt. Loads the MCP tools over HTTP and drives Claude. Exposes a sync `run_agent()`. |
| Frontend | [`frontend/`](frontend/) | Flask chat UI + `POST /chat`. Renders the agent's Markdown answer and shows which tools it used. |

### The MCP tools

| Tool | What it does |
|------|--------------|
| `get_series_data(series_id, start_date, end_date)` | Historical observations for a FRED series (trends). |
| `get_latest_value(series_id)` | The single most recent value ("what is X now"). |
| `search_series(keyword)` | Find FRED series by topic when the ID is unknown. |
| `compare_series(id1, id2, start_date, end_date)` | Two series over the same window (relationships). |
| `get_category_snapshot(topic, top_n)` | A multi-indicator "state of X" overview — top series for a topic, each with latest value + YoY change (uses FRED's native `pc1`/`ch1` transforms). |
| `get_demand_pulse(months_back)` | Composite read on whether consumer demand is strengthening or weakening — a fixed set of demand indicators each tagged improving/deteriorating/flat, plus an overall pulse label (pure arithmetic, no LLM). |

---

## Tech stack

- **MCP server:** [FastMCP](https://gofastmcp.com) (Streamable HTTP transport)
- **Agent:** [LangGraph](https://langchain-ai.github.io/langgraph/) `create_react_agent`, `langchain-mcp-adapters`, `langchain-anthropic`
- **LLM:** Claude Sonnet (`claude-sonnet-4-6`)
- **Frontend:** Flask + gunicorn (production), vanilla JS, server-side Markdown rendering
- **Data:** [FRED API](https://fred.stlouisfed.org/docs/api/fred/)
- **Runtime:** Python 3.11, Docker / Docker Compose

---

## Prerequisites

- **[Docker Desktop](https://www.docker.com/products/docker-desktop/)** running (for the recommended path), **or** Python 3.11+ for local dev.
- A **free FRED API key** and an **Anthropic API key** (see below).

### Get your API keys

| Key | Where | Cost |
|-----|-------|------|
| `FRED_API_KEY` | https://fred.stlouisfed.org/docs/api/api_key.html | Free |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com/settings/keys | Paid (usage-based) |

---

## Quick start (Docker — recommended)

```bash
git clone <your-repo-url>
cd InMarket_Project

# 1. Create your .env from the template and paste in your keys
#    (PowerShell)  Copy-Item .env.example .env
#    (bash)        cp .env.example .env
#    then edit .env: set FRED_API_KEY and ANTHROPIC_API_KEY

# 2. Build and run both containers
docker compose up --build
```

Then open **http://localhost:5000**.

> [!IMPORTANT]
> Open **`http://localhost:5000`** — **not** `http://0.0.0.0:5000`.
> `0.0.0.0` is the address the server *binds to inside the container*, not a URL
> you can visit; a browser will show **`ERR_ADDRESS_INVALID`**. The startup log
> prints a clickable `http://localhost:5000` line — use that one. (`127.0.0.1`
> works too.)

> The first build takes a few minutes (installs LangGraph / LangChain / Anthropic
> / FastMCP). The `mcp_server` container starts first; the `web` container waits
> for it to be healthy, then serves the UI. Only `:5000` is published to your
> machine — the MCP server stays on the internal Docker network.

Stop with `Ctrl+C`, or `docker compose down`.

---

## Try it — example questions

The UI's clickable chips cover the basics — *unemployment rate*, *consumer
sentiment trend*, *labor-market snapshot*, and *unemployment vs. inflation*.
Here are more to type in that show off the rest of the tools:

| Question | What it demonstrates |
|----------|----------------------|
| *Is U.S. consumer demand strengthening or weakening right now?* | Composite demand read with a deterministic verdict — `get_demand_pulse` |
| *Give me a snapshot of the housing market.* | Multi-indicator sector snapshot — `get_category_snapshot` |
| *How have gas prices moved relative to overall inflation over the past 3 years?* | Resolves an unfamiliar topic, then compares two series — `search_series` → `compare_series` |
| *What are 30-year mortgage rates right now?* | Finds the right series, returns its latest value — `get_latest_value` |
| *What's the current federal funds rate?* | A clean single latest value on another series |

Every answer cites the FRED **series IDs, units, and dates** it used, so you can
verify the numbers against [fred.stlouisfed.org](https://fred.stlouisfed.org/).

---

## Run locally without Docker (dev workflow)

```powershell
cd InMarket_Project
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # bash: source .venv/bin/activate
pip install -r requirements.txt
Copy-Item .env.example .env           # then add your keys
```

Open **two terminals** (both with the venv activated):

```powershell
# Terminal A — MCP server
python -m mcp_server.server           # serves http://127.0.0.1:8000/mcp/

# Terminal B — Flask app
python -m frontend.app                # serves http://127.0.0.1:5000
```

Open **http://127.0.0.1:5000**.

### Smoke tests (optional)

```powershell
# MCP tools (in-memory; no server needed)
python -m mcp_server.smoke_test
# MCP tools over HTTP (server must be running)
python -m mcp_server.smoke_test http://127.0.0.1:8000/mcp/
# Full agent, end-to-end (MCP server must be running)
python -m agent.smoke_test
```

---

## Evaluation

A small eval harness ([`eval/`](eval/)) checks that the agent gives **correct,
grounded** answers — not just plausible-sounding ones:

- **L1 — routing:** did the agent call the right tool/series for the question?
- **L2 — grounding:** are the stated numbers actually correct? Ground truth is
  resolved **live** by calling the MCP tools (which hit FRED), so the suite never
  goes stale — each check asserts the real value *and* the series ID appear in
  the answer, and the demand case asserts the agent's verdict matches
  `get_demand_pulse`'s deterministic `pulse` label.

Run it (MCP server must be running):

```powershell
python -m eval.run_eval
```

Latest run:

```
CASE                        L1 ROUTING  L2 GROUNDING  DETAIL
current_unemployment        PASS        PASS          UNRATE=4.3 id:OK val:OK
consumer_sentiment_trend    PASS        PASS          UMCSENT=49.8 id:OK val:OK
unemployment_vs_inflation   PASS        PASS          UNRATE=4.3 ...; CPIAUCSL=333.98 ...
labor_market_snapshot       PASS        N/A
demand_pulse                PASS        PASS          pulse=softening OK
mortgage_rate_now           PASS        PASS          MORTGAGE30US=6.47 id:OK val:OK

L1 routing:   6/6 passed
L2 grounding: 5/5 passed (excludes N/A)
```

---

## Configuration

All configuration is via environment variables (loaded from `.env`):

| Variable | Required | Default | Notes |
|----------|:--:|---------|-------|
| `FRED_API_KEY` | ✅ | — | FRED API key (used by the MCP server). |
| `ANTHROPIC_API_KEY` | ✅ | — | Anthropic key (used by the agent). |
| `ANTHROPIC_MODEL` | | `claude-sonnet-4-6` | Claude model the agent uses. |
| `MCP_HOST` / `MCP_PORT` | | `0.0.0.0` / `8000` | MCP server bind address. |
| `MCP_SERVER_URL` | | `http://127.0.0.1:8000/mcp/` | Where the agent finds the MCP server. Compose sets this to `http://mcp_server:8000/mcp/`. |
| `FLASK_HOST` / `FLASK_PORT` | | `0.0.0.0` / `5000` | Flask bind (local dev only). |
| `FLASK_DEBUG` | | `false` | Never enable in production. |

---

## Project structure

```
Inmarket/
├── mcp_server/
│   ├── server.py          # FastMCP server: 6 FRED tools
│   ├── fred_client.py     # async FRED REST client (httpx)
│   └── smoke_test.py
├── agent/
│   ├── agent.py           # LangGraph ReAct agent + sync run_agent()
│   ├── mcp_client.py      # loads MCP tools over HTTP
│   ├── prompts.py         # system prompt
│   └── smoke_test.py
├── frontend/
│   ├── app.py             # Flask app + POST /chat
│   ├── templates/index.html
│   └── static/{style.css, chat.js}
├── eval/                  # agent eval — routing + grounding checks
│   ├── cases.py
│   └── run_eval.py
├── Dockerfile             # one image for both services
├── docker-compose.yml     # mcp_server (internal) + web (:5000)
├── .dockerignore
├── requirements.txt
├── requirements-dev.txt   # dev/security tooling (pip-audit)
├── .env.example           # template — copy to .env (never committed)
└── README.md
```

---

## Security

Implemented:

- **Secrets never committed or baked in** — `.env` is gitignored and excluded by
  `.dockerignore`; keys are injected at runtime via Compose env interpolation.
- **Least-privilege tools** — all 6 MCP tools are *read-only* FRED lookups; no
  write/delete/shell/filesystem access (OWASP LLM "Excessive Agency").
- **No SSRF** — the MCP server only ever calls a fixed FRED host; no
  user-supplied URLs.
- **Container hardening** — non-root user, slim base image pinned by digest,
  production gunicorn server, and the unauthenticated MCP server is **not
  exposed** to the host (internal network only). The frontend binds to loopback.
- **Bounded model output** via `max_tokens`.
- **Output sanitization (XSS)** — the model's answer is rendered to HTML and
  allowlist-sanitized with `nh3` (no `<script>`/`<img>`, event handlers, or
  `javascript:` URLs) before it reaches the browser (OWASP LLM05 / A03).
- **No internal error leakage** — exceptions are logged server-side; the client
  receives only a generic message (OWASP LLM02).
- **Security response headers** — `Content-Security-Policy`, `X-Frame-Options`,
  `X-Content-Type-Options`, `Referrer-Policy`, and `Permissions-Policy` on every
  response (OWASP A05).
- **Request & error logging** — every request (method, path, status, latency)
  and any failures are logged server-side (OWASP A09).
- **Pinned & audited dependencies** — all direct deps are pinned to exact
  versions and the Docker base image is pinned by digest; `pip-audit` reports no
  known CVEs (OWASP LLM03 / A06). Re-check with `pip-audit -r requirements.txt`.
- **"Not financial advice" disclaimer** — a standing UI disclaimer marks answers
  as informational FRED data, not financial or investment advice; the system
  prompt also forbids giving investment advice (OWASP LLM09 — misinformation).

Planned hardening (tracked against OWASP Web + LLM Top 10):

- Rate limiting + input-length cap + bounded tool parameters (OWASP LLM10).

References : 

OWASP TOP 10 :-
 - https://genai.owasp.org/llm-top-10/
 - https://owasp.org/Top10/2025/

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ERR_ADDRESS_INVALID` at `http://0.0.0.0:5000` | Use **`http://localhost:5000`**. `0.0.0.0` is a bind address, not a browsable URL. |
| `docker: ... dockerDesktopLinuxEngine ... cannot find the file` | Start **Docker Desktop** first. |
| Compose error: `set FRED_API_KEY in .env` | Create `.env` from `.env.example` and fill in your keys. |
| Agent error / connection refused on first chat | Ensure the **MCP server** is running (Terminal A locally, or the `mcp_server` container is healthy). |
| Port 5000 already in use | Local dev: `$env:FLASK_PORT=5001; python -m frontend.app`. Docker: change the host port in `docker-compose.yml`. |

---

## Notes for a developer taking this over

- The agent is **in-process** with Flask (`from agent.agent import run_agent`).
  Because Flask is synchronous but the agent/MCP stack is async, `agent.py` runs
  a single long-lived background event loop and dispatches requests onto it —
  see the comments there before refactoring.
- Tool *docstrings* in `mcp_server/server.py` are the descriptions the LLM reads;
  the *system prompt* in `agent/prompts.py` steers tool selection and answer
  formatting. Both are the main levers for behavior changes.
