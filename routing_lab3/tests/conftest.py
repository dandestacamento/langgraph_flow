"""Shared pytest fixtures for the Routing Accuracy Lab test suite."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure `routing_lab/` (the project root, one level above this file's parent)
# is importable as `app.*` regardless of the directory pytest is invoked
# from.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import find_dotenv, load_dotenv  # noqa: E402

# find_dotenv() walks upward from this file, so it locates the repo-root
# .env (routing_lab/ has no .env of its own) regardless of the pytest cwd.
load_dotenv(find_dotenv())

from app.cache import enable_llm_cache  # noqa: E402
from app.config import CHROMA_PERSIST_DIR  # noqa: E402
from app.graph import build_graph  # noqa: E402

enable_llm_cache()  # cheap/no-op if ROUTING_LAB_CACHE_ENABLED=0; see app/cache.py

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


@pytest.fixture(scope="session", autouse=True)
def ensure_chroma_index_exists():
    """Level 4+ tests need the Chroma vector index built (see
    scripts/build_index.py). Build it automatically on a fresh checkout
    so `pytest` works without a manual step - but don't rebuild it every
    run; it's deterministic from `knowledge_base/`, so an existing index
    is left alone (re-run scripts/build_index.py by hand after editing
    the knowledge base generation script).

    Checks for `manifest.json` specifically, not just the `.chroma/`
    directory's existence - `CHROMA_PERSIST_DIR` can exist but be empty
    (e.g. Chroma's client lazily creates the directory as a side effect
    of being instantiated at all, even with zero data added yet, if
    something touches `get_vector_store()` before `build_index.py` ever
    runs) and `.exists()` alone can't tell that apart from a real,
    populated index - `manifest.json` is only ever written at the end of
    a successful `build_index.py` run, so its presence is a much safer
    signal."""
    if not (CHROMA_PERSIST_DIR / "manifest.json").exists():
        from scripts.build_index import main as build_index

        build_index()


@pytest.fixture(scope="session")
def compiled_graph():
    """Build the graph once per test session - each test invokes it fresh
    with its own question, but the compiled StateGraph object is reusable."""
    return build_graph()
