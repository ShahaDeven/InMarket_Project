"""
Eval cases: each is a question plus the checks to run against the answer.

  required_tools : L1 routing — these tool names must appear in the agent's
                   tool_calls (extra calls like search_series are allowed).
  grounding      : L2 grounding — checks resolved to live ground truth by the
                   runner (it calls the MCP tools), so values never go stale:
                     {"type": "latest_value", "series_id": "X"}
                         the latest FRED value for X *and* the id "X" must
                         appear in the answer.
                     {"type": "pulse"}
                         the agent's verdict must match get_demand_pulse's
                         deterministic `summary.pulse` label.
"""

CASES = [
    {
        "name": "current_unemployment",
        "question": "What's the current U.S. unemployment rate?",
        "required_tools": {"get_latest_value"},
        "grounding": [{"type": "latest_value", "series_id": "UNRATE"}],
    },
    {
        "name": "consumer_sentiment_trend",
        "question": "How has consumer sentiment changed over the past year?",
        "required_tools": {"get_series_data"},
        "grounding": [{"type": "latest_value", "series_id": "UMCSENT"}],
    },
    {
        "name": "unemployment_vs_inflation",
        "question": "Compare unemployment and inflation since 2020.",
        "required_tools": {"compare_series"},
        "grounding": [
            {"type": "latest_value", "series_id": "UNRATE"},
            {"type": "latest_value", "series_id": "CPIAUCSL"},
        ],
    },
    {
        "name": "labor_market_snapshot",
        "question": "How's the labor market doing?",
        "required_tools": {"get_category_snapshot"},
        # Series set is dynamic (search-by-popularity) — routing only, no L2.
        "grounding": [],
    },
    {
        "name": "demand_pulse",
        "question": "Is U.S. consumer demand strengthening or weakening right now?",
        "required_tools": {"get_demand_pulse"},
        "grounding": [{"type": "pulse"}],
    },
    {
        "name": "mortgage_rate_now",
        "question": "What is the current 30-year fixed mortgage rate?",
        "required_tools": {"get_latest_value"},
        "grounding": [{"type": "latest_value", "series_id": "MORTGAGE30US"}],
    },
]
