"""Shared pytest fixtures for the Routing Accuracy Lab test suite."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure `routing/` (the project root, one level above this file's parent)
# is importable as `app.*` regardless of the directory pytest is invoked
# from.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import find_dotenv, load_dotenv  # noqa: E402

# find_dotenv() walks upward from this file, so it locates the repo-root
# .env (routing/ has no .env of its own) regardless of the pytest cwd.
load_dotenv(find_dotenv())

from app.graph import build_graph  # noqa: E402

GROUND_TRUTH_PATH = _PROJECT_ROOT / "datasets" / "routing_ground_truth.jsonl"


def load_ground_truth(level: int | None = None) -> list[dict]:
    rows = []
    with GROUND_TRUTH_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if level is None or row["level"] == level:
                rows.append(row)
    return rows


@pytest.fixture(scope="session")
def compiled_graph():
    """Build the graph once per test session - each test invokes it fresh
    with its own question, but the compiled StateGraph object is reusable."""
    return build_graph()
