"""Gunicorn config for the InMarket web service (used inside the Docker image).

Note on the bind address: gunicorn binds 0.0.0.0:5000 *inside the container* so
Docker can forward host traffic to it. That is required — binding 127.0.0.1
inside the container would make it unreachable from the host. From your machine,
open http://localhost:5000 (0.0.0.0 is a bind address, not a browsable URL).
"""

bind = "0.0.0.0:5000"
workers = 1      # keep the agent's singleton background-loop runtime coherent
threads = 8      # concurrency within the single worker
timeout = 120    # LLM + tool round-trips can exceed 30s


def when_ready(server):
    # Printed once the server is up — a clickable, working URL for the user.
    server.log.info("InMarket is ready  →  open  http://localhost:5000")
