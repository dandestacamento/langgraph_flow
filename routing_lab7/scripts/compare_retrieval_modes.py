"""Benchmarks similarity, MMR, and hybrid retrieval against Level 4 (single-chapter recall)
and Level 6 (multi-chapter coverage) ground truth, per
instructions/learnings/routing-lab2-learnings.md section 4 (P1) - this is
the validation harness that decides whether hybrid retrieval and/or
reranking should ever become the default, instead of just assuming they
help.

Calls `app.rag.retrieval.retrieve()` directly (not the full graph) with
each row's already-known expected topic/subtopic, since retrieval quality
in isolation - not routing - is what's being measured here. Scored with
the same `RetrievalResult`/`MultiChapterRetrievalResult` classes
`tests/test_rag_retrieval.py`/`tests/test_multichapter_evidence.py` use,
so the numbers mean exactly the same thing as those tests' baseline.

Usage:
    python scripts/compare_retrieval_modes.py
    python scripts/compare_retrieval_modes.py --save experiments/retrieval_mode_comparison.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import find_dotenv, load_dotenv  # noqa: E402

load_dotenv(find_dotenv())

from app.cache import enable_llm_cache  # noqa: E402
from app.config import RETRIEVAL_TOP_K  # noqa: E402
from app.evaluation.retrieval_metrics import (  # noqa: E402
    MultiChapterRetrievalResult,
    RetrievalResult,
    summarize_multichapter_retrieval,
    summarize_retrieval,
)
from app.rag.retrieval import retrieve  # noqa: E402

enable_llm_cache()

GROUND_TRUTH_PATH = PROJECT_ROOT / "datasets" / "routing_ground_truth.jsonl"

# Each mode's keyword args to app.rag.retrieval.retrieve(). "similarity" is
# the current default (0 benchmarked reason to change it per Level 4's
# 100% baseline Recall@K); "hybrid" and "hybrid+rerank" are the P1
# capabilities this script exists to validate before either one is
# trusted.
MODES: dict[str, dict] = {
    "similarity": {"retrieval_mode": "similarity", "use_reranking": False},
    "mmr": {"retrieval_mode": "mmr", "use_reranking": False},
    "hybrid": {"retrieval_mode": "hybrid", "use_reranking": False},
    "hybrid+rerank": {"retrieval_mode": "hybrid", "use_reranking": True},
}


def load_ground_truth() -> list[dict]:
    rows = []
    with GROUND_TRUTH_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _retrieve_and_time(question: str, topic: str, subtopic: str, mode_kwargs: dict) -> tuple[list[dict], float]:
    start = time.perf_counter()
    passages = retrieve(question, topic=topic, subtopic=subtopic, top_k=RETRIEVAL_TOP_K, **mode_kwargs)
    latency_ms = (time.perf_counter() - start) * 1000
    return passages, latency_ms


def run_level_4(rows: list[dict], mode_name: str, mode_kwargs: dict) -> tuple[list[RetrievalResult], list[float]]:
    results, latencies = [], []
    for row in rows:
        passages, latency_ms = _retrieve_and_time(
            row["question"], row["expected_topics"][0], row["expected_subtopic"], mode_kwargs
        )
        latencies.append(latency_ms)
        results.append(
            RetrievalResult(
                question_id=row["id"],
                expected_chapter=row.get("expected_chapter"),
                retrieved_chapter_ids=[p["chapter_id"] for p in passages],
            )
        )
    return results, latencies


def run_level_6(rows: list[dict], mode_name: str, mode_kwargs: dict) -> tuple[list[MultiChapterRetrievalResult], list[float]]:
    results, latencies = [], []
    for row in rows:
        passages, latency_ms = _retrieve_and_time(
            row["question"], row["expected_topics"][0], row["expected_subtopic"], mode_kwargs
        )
        latencies.append(latency_ms)
        results.append(
            MultiChapterRetrievalResult(
                question_id=row["id"],
                expected_chapters=row["expected_chapters"],
                retrieved_chapter_ids=[p["chapter_id"] for p in passages],
            )
        )
    return results, latencies


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--save", type=str, default=None, help="Path to save raw per-question results as JSON.")
    args = parser.parse_args()

    all_rows = load_ground_truth()
    l4_rows = [r for r in all_rows if r["level"] == 4]
    l6_rows = [r for r in all_rows if r["level"] == 6]
    print(f"Benchmarking {len(MODES)} retrieval modes on {len(l4_rows)} Level 4 + {len(l6_rows)} Level 6 questions\n")

    summary: dict[str, dict] = {}
    raw_results: dict[str, dict] = {}

    for mode_name, mode_kwargs in MODES.items():
        print(f"Running mode: {mode_name}...")
        l4_results, l4_latencies = run_level_4(l4_rows, mode_name, mode_kwargs)
        l6_results, l6_latencies = run_level_6(l6_rows, mode_name, mode_kwargs)

        l4_summary = summarize_retrieval(l4_results)
        l6_summary = summarize_multichapter_retrieval(l6_results)
        avg_latency = sum(l4_latencies + l6_latencies) / len(l4_latencies + l6_latencies)

        summary[mode_name] = {"level_4": l4_summary, "level_6": l6_summary, "avg_latency_ms": round(avg_latency, 1)}
        raw_results[mode_name] = {
            "level_4": [
                {"question_id": r.question_id, "expected_chapter": r.expected_chapter,
                 "retrieved_chapter_ids": r.retrieved_chapter_ids, "is_recalled": r.is_recalled}
                for r in l4_results
            ],
            "level_6": [
                {"question_id": r.question_id, "expected_chapters": r.expected_chapters,
                 "retrieved_chapter_ids": r.retrieved_chapter_ids, "is_fully_covered": r.is_fully_covered,
                 "coverage_fraction": r.coverage_fraction}
                for r in l6_results
            ],
        }

    print("\n" + "=" * 78)
    print("RESULTS")
    print("=" * 78)
    header = f"{'Mode':<16}{'L4 Recall@K':>14}{'L6 Full Coverage':>18}{'L6 Avg Coverage':>18}{'Avg ms':>10}"
    print(header)
    print("-" * len(header))
    for mode_name, data in summary.items():
        print(
            f"{mode_name:<16}"
            f"{100 * data['level_4']['recall_at_k']:>13.0f}%"
            f"{100 * data['level_6']['multichapter_coverage']:>17.0f}%"
            f"{100 * data['level_6']['avg_coverage_fraction']:>17.0f}%"
            f"{data['avg_latency_ms']:>10.0f}"
        )

    if args.save:
        save_path = Path(args.save)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(
            json.dumps({"summary": summary, "raw_results": raw_results}, indent=2),
            encoding="utf-8",
        )
        print(f"\nSaved full results to {save_path}")


if __name__ == "__main__":
    main()
