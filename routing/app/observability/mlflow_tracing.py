"""MLflow tracing helper.

MLflow in this workspace runs on-demand only (see start_mlflow.ps1 at the
repo root) - it is never auto-started at login, at computer restart, or as
a background service. `mlflow.set_experiment()` blocks (effectively
hangs the caller) when the tracking server isn't reachable, so this does a
fast, non-blocking socket check first and simply skips tracing if the
server isn't up, rather than freezing the app or test run.
"""

from __future__ import annotations

import os
import socket
from urllib.parse import urlparse

DEFAULT_TRACKING_URI = "http://127.0.0.1:5000"
EXPERIMENT_NAME = "langgraph_routing_lab"


def enable_mlflow_tracing_if_available(
    tracking_uri: str | None = None,
    experiment: str = EXPERIMENT_NAME,
    timeout: float = 0.5,
) -> bool:
    """Enable MLflow LangChain/LangGraph autologging only if the tracking
    server is actually reachable. Returns True if tracing was enabled."""
    tracking_uri = tracking_uri or os.environ.get("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI)
    parsed = urlparse(tracking_uri)
    host, port = parsed.hostname or "127.0.0.1", parsed.port or 80
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError:
        return False

    import mlflow

    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(experiment)
    mlflow.langchain.autolog()
    return True
