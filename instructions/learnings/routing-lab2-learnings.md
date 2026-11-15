# Improving `routing_lab2/` with `rag_krish` patterns (routing-lab2)

> **Status: implemented.** This document was written as the pre-implementation plan for the
> `feature/routing-lab2` branch, based on reading `routing_lab/` before the user copied it to
> `routing_lab2/` for this branch's work - all code examples and links below point to
> `routing_lab2/`, where the implementation actually happened (`routing_lab/` itself was never
> modified). See §7 for what was actually built, what the benchmark found, and what was decided -
> plus a second round of fixes (from a different self-review document) that this plan never
> covered. Commits: `5fd6a46` (P1 hybrid/rerank + P2 incremental indexing), `aa38803`
> (run_evaluations.py/SQL guard/synthesis-citation fixes).

This document is the design/triage brief for the `feature/routing-lab2` branch: it re-reads
[rag-krish-learnings.md](./rag-krish-learnings.md) and the actual source in
[reference/rag_krish/rag/](../../reference/rag_krish/rag/) side-by-side with the **then-current**
state of [routing_lab2/app/rag/](../../routing_lab2/app/rag/) (post `routing/` → `routing_lab/`
rename) to answer one question precisely: *what should actually change in `routing_lab2/`, and
in what order?*

It deliberately does **not** start from "port everything rag_krish does." It starts from
`routing_lab2/`'s own measured evidence, because that's this project's own house style (see the
README's "Two real findings, fixed" sections under Level 4/6/9 - every past change was driven by
an observed failure, not a speculative improvement) - and that evidence changes the priority order
a naive side-by-side comparison would suggest.

---

## 1. The evidence that must drive this decision

Before recommending anything, the project's own README already reports, for Level 4 (RAG
retrieval), using plain Chroma similarity search with no hybrid/reranking:

> **19/19 answerable Level 4 questions recall the expected chapter (100% Retrieval Recall@K,
> k=3) and produce a correctly grounded, cited answer; all 3 deliberately unanswerable questions
> correctly report insufficient information instead of fabricating an answer.**

And the one retrieval-adjacent miss that *was* found (Level 6, a compound question needing two
chapters from the same subtopic) was fixed by **raising `RETRIEVAL_TOP_K` from 3 to 5**
([app/config.py](../../routing_lab2/app/config.py)) - not by adding hybrid search or reranking.
The other two real findings recorded in the README (the APR/APY subtopic-routing gap, and
LLM-level generation non-determinism) aren't retrieval problems at all - one is a routing/config
fix, the other is a prompting fix.

**Conclusion: on the current 57-chapter / 68-chunk knowledge base and its 228-row ground truth,
retrieval is not the bottleneck.** That doesn't make `rag_krish`'s retrieval patterns irrelevant
- it means they should be framed as **capabilities to have in reserve, benchmarked before being
trusted**, not as urgent fixes. This reframing is the main difference between this document and
a "just port it" plan, and it changes the recommended priority order below.

---

## 2. What `routing_lab2/`'s RAG pipeline looked like before this round

| Concern | Current implementation |
|---|---|
| Ingestion | [app/rag/ingestion.py](../../routing_lab2/app/rag/ingestion.py) parses Markdown chapters (YAML front matter + H1 + body) - knowledge-base content only; CSV/JSON/TXT are deliberately handled by dedicated tools (`sql_query`, `metadata_lookup`), not RAG |
| Chunking | [app/rag/chunking.py](../../routing_lab2/app/rag/chunking.py) - one strategy, blank-line paragraph splitting, no size/overlap target (chapters are 1-2 paragraphs each, so this is intentionally simple) |
| Embeddings | [app/rag/embeddings.py](../../routing_lab2/app/rag/embeddings.py) - `text-embedding-3-small`, wrapped in `CachedEmbeddings` ([app/cache.py](../../routing_lab2/app/cache.py)) - a persistent SQLite cache keyed by `(model, text)` |
| Index | [scripts/build_index.py](../../routing_lab2/scripts/build_index.py) - **always a full rebuild**: deletes every existing ID, re-adds every current chunk, every run |
| Retrieval | [app/rag/retrieval.py](../../routing_lab2/app/rag/retrieval.py) - Chroma `similarity_search_with_score` only, filtered by `{topic}` or `{topic, subtopic}`, `RETRIEVAL_TOP_K = 5` |
| Reranking | [app/rag/reranking.py](../../routing_lab2/app/rag/reranking.py) - explicit `NotImplementedError` stub, with a docstring saying it's deferred "once baseline Retrieval Recall@K results justify adding it" |
| Query rewriting | none |
| Evaluation | deterministic: `RetrievalResult`/`MultiChapterRetrievalResult` in [app/evaluation/retrieval_metrics.py](../../routing_lab2/app/evaluation/retrieval_metrics.py), exact `chapter_id` membership, no LLM judge |

Two things are easy to miss but matter a lot for what follows:

1. **The embedding-cost problem `rag_krish`'s manifest solves is already half-solved here.**
   `CachedEmbeddings` means re-running `build_index.py` after an unrelated change doesn't re-bill
   for unchanged chunks - it just re-does the (cheap, local) Chroma delete/add churn. The manifest
   pattern's *remaining* value for `routing_lab2/` is about **index operation safety and speed at
   scale**, not API cost.
2. **`retrieve()` always applies a `{topic}` or `{topic, subtopic}` metadata filter.**
   `rag_krish`'s hybrid retriever (`EnsembleRetriever` over the *entire* docstore) can't be
   dropped in unmodified - a BM25 index has to be built per filtered subset (see §4b), not once
   globally, or hybrid search would stop respecting topic/subtopic scoping and silently return
   chunks from the wrong domain.

---

## 3. What `rag_krish` offers (recap, see [rag-krish-learnings.md §3](./rag-krish-learnings.md))

From [reference/rag_krish/rag/manifest.py](../../reference/rag_krish/rag/manifest.py),
[core.py](../../reference/rag_krish/rag/core.py), [retrieval.py](../../reference/rag_krish/rag/retrieval.py),
and [splitting.py](../../reference/rag_krish/rag/splitting.py):

- **Manifest-based incremental indexing**: per-file `mtime`/`size` prefilter, content-addressed
  chunk IDs, an `ingest_signature` (`splitter:chunk_size:chunk_overlap:embedding_model`) that
  forces a full rebuild on config drift, and (FAISS-specific) a content-hash rename detector that
  reuses existing vectors via `index.reconstruct`.
- **Hybrid retrieval**: `EnsembleRetriever([vector_retriever, BM25Retriever], weights=[0.7, 0.3])`.
- **Cross-encoder reranking**: fetch a larger candidate pool (`RERANK_FETCH_K=10`), rerank with a
  small CPU-friendly cross-encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`, ~80MB), narrow back to
  `RETRIEVAL_K`.
- **Pluggable splitters**: recursive/character/token/semantic, selected by one factory function.
- **Query expansion**: one LLM rewrite of the question before retrieval, optional.
- **Central config with validated allow-lists**: constructor-time `ValueError` on an invalid
  `splitter_type`/`embedding_model`/`retrieval_mode`/`query_enhancement`.

---

## 4. Prioritized recommendations

### P1 (do first): implement hybrid retrieval + reranking as an **opt-in, benchmarked** capability

Not because current recall is bad (it isn't) but because:
- The knowledge base's own content is full of exact, low-semantic-similarity tokens that are
  exactly what embedding search misses and BM25 excels at - fault codes (`E01`/`E21`/`E3`),
  acronyms (`APR`/`APY`, `RBAC`, `ADF`), model numbers, and the README already documents one near
  miss in this exact territory (the APR/APY subtopic misclassification).
- `reranking.py` is a stub with a docstring that explicitly invites this once there's a reason -
  implementing it behind a flag, benchmarked, *is* satisfying that invitation correctly: with
  evidence, not speculation.
- It's directly, cheaply measurable with infrastructure that already exists - no new metrics code
  needed, just a new experiment script.

**Design, adapted for Chroma's per-(topic, subtopic) metadata filtering** (the one real
adaptation `rag_krish`'s code needs - its `EnsembleRetriever` assumes one global, unfiltered
corpus):

```python
# app/rag/retrieval.py - additive, default behavior (similarity-only) unchanged
from functools import lru_cache
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

@lru_cache(maxsize=None)
def _bm25_retriever(topic: str, subtopic: str | None, top_k: int) -> BM25Retriever:
    """A small BM25 index scoped to exactly one (topic, subtopic) pair - not
    the whole collection - so hybrid retrieval still respects the same
    scoping as similarity_search_with_score's `where` filter. Cheap to
    build (a few dozen chunks per pair) and cached per pair for the
    process lifetime, same lifetime as get_vector_store()."""
    where = {"topic": topic} if subtopic is None else {"$and": [{"topic": topic}, {"subtopic": subtopic}]}
    raw = get_vector_store().get(where=where, include=["documents", "metadatas"])
    docs = [Document(page_content=t, metadata=m) for t, m in zip(raw["documents"], raw["metadatas"])]
    retriever = BM25Retriever.from_documents(docs)
    retriever.k = top_k
    return retriever
```

Then a `retrieval_mode: str = "similarity"` parameter on `retrieve()` that, for `"hybrid"`, merges
the BM25 hits with the vector hits (e.g. reciprocal-rank fusion, or LangChain's
`EnsembleRetriever` over the two scoped retrievers) before converting back to `routing_lab2/`'s
existing `dict` shape. Reranking follows the same `build_reranking_retriever` shape as
`rag_krish`, fetching a larger pool (e.g. `top_k=10`) only when reranking is enabled, then
narrowing to `RETRIEVAL_TOP_K`.

**Validation plan - mirror `compare_architectures.py`, don't invent a new harness:** add
`scripts/compare_retrieval_modes.py` that runs the Level 4 and Level 6 ground-truth rows through
`retrieve()` directly (no need to run the full graph) under `similarity` / `hybrid` /
`hybrid+rerank`, scoring with the *existing* `RetrievalResult`/`MultiChapterRetrievalResult`
classes from `app/evaluation/retrieval_metrics.py`. Report Recall@K and multi-chapter coverage
side by side, the same table shape `compare_architectures.py` already prints. **Only change the
default `retrieval_mode` if this experiment shows a real, reproducible win** - if it doesn't
(plausible, given the 100% baseline), keep hybrid/reranking available but non-default, and record
the negative result in the README the same way the project already records "two real findings" -
a documented null result ("tried hybrid retrieval, no measurable improvement over similarity at
current KB size - revisit if KB grows past N chapters") is itself valuable and exactly this
project's style.

### P2 (do soon, cheap insurance): manifest-based incremental indexing for `build_index.py`

Lower urgency than P1 (no observed problem today), but genuinely cheap to add and pays off before
it's urgent rather than after:

- **Reframe the goal**: not "stop re-billing embeddings" (already solved by `CachedEmbeddings`)
  but "stop doing a full Chroma delete-all/add-all on every run, regardless of whether anything
  changed" - this matters once the knowledge base is 10x or 50x its current size (the project has
  already grown its test coverage incrementally across Levels 1-10; the knowledge base itself may
  well grow the same way).
- **Keep `routing_lab2/`'s existing positional chunk-ID scheme**
  (`{document_id}:{chapter_id}:{chunk_index}`) rather than switching to `rag_krish`'s
  content-addressed SHA-256 chunk IDs - positional IDs are simpler and fine as long as a changed
  file's *entire* chunk set is replaced atomically (delete old IDs for that file, add new ones),
  which is exactly what incremental sync needs to do per-file anyway.
- **Skip the FAISS-specific rename/vector-reuse optimization.** It requires `index.reconstruct()`
  (FAISS-only - Chroma's nearest equivalent is `collection.get(..., include=["embeddings"])`,
  which is a legitimate substitute if ever needed) to avoid one embedding API call per renamed
  file. Since the knowledge base is generated wholesale by
  [scripts/generate_knowledge_base.py](../../routing_lab2/scripts/generate_knowledge_base.py)
  rather than hand-edited file-by-file, renames are rare to nonexistent in practice - this is the
  one `rag_krish` feature with the worst effort-to-value ratio here and should be left out.

**Design sketch**:

```python
# app/rag/manifest.py (new) - mtime/size prefilter only; no content hashing needed
# since routing_lab's chunk ids are already stable per unchanged file.
import json
from pathlib import Path

def scan_chapter_stats(knowledge_base_dir: Path) -> dict[str, dict]:
    """relative_path -> {mtime, size} for every *.md chapter file."""
    ...

def load_manifest(path: Path) -> dict: ...
def save_manifest(path: Path, data: dict) -> None: ...
```

```python
# scripts/build_index.py - extend main() with an incremental path
def main(force_rebuild: bool = False) -> None:
    manifest = load_manifest(MANIFEST_PATH)
    current_stats = scan_chapter_stats(KNOWLEDGE_BASE_DIR)
    changed = {p for p, s in current_stats.items() if manifest.get("files", {}).get(p) != s}
    deleted = set(manifest.get("files", {})) - set(current_stats)

    if force_rebuild or not manifest.get("files") or manifest.get("ingest_signature") != INGEST_SIGNATURE:
        # existing full-rebuild path, unchanged
        ...
    elif not changed and not deleted:
        print("No chapters changed - index already up to date.")
        return
    else:
        # delete this file's old chunk ids, re-chunk + re-embed only `changed`
        # chapters (embedding calls still hit CachedEmbeddings first)
        ...
```

Where `INGEST_SIGNATURE` is a one-line analogue of `rag_krish`'s `_ingest_signature()` -
`f"{chunking_strategy_version}:{EMBEDDING_MODEL}"` - so a future chunking-logic change forces a
full rebuild automatically instead of silently leaving stale chunks from the old splitting logic
behind.

**Validation plan**: `pytest tests/test_rag_retrieval.py` (Level 4, 43 tests) and
`tests/test_multichapter_evidence.py` (Level 6) must still pass unchanged after switching
`build_index.py` to the incremental path; additionally, assert that running `build_index.py`
twice in a row with no content changes is a true no-op (no Chroma writes) - a regression test
`rag_krish` itself doesn't have but is worth adding here given it's the whole point of the change.

### P3 (defer - low value given current scale and design)

- **Query expansion**: `routing_lab2/`'s pipeline already does LLM-driven query narrowing via
  `topic_router`/`subtopic_router`/multi-hop decomposition before retrieval ever runs - adding
  `rag_krish`'s generic "expand with synonyms" rewrite on top is likely redundant with work the
  graph already does, and unlike P1/P2 it has no existing evaluation hook that would show whether
  it helped. Skip unless a *specific* retrieval failure is observed that's attributable to a
  too-terse query, not a scoping problem.
- **Pluggable/semantic chunking**: chapters are 1-2 paragraphs each by design (see
  [generate_knowledge_base.py](../../routing_lab2/scripts/generate_knowledge_base.py)); paragraph
  splitting already produces exactly the per-fact chunk granularity the citation requirement
  needs. Token/semantic splitters solve a problem (chunking long documents well) this knowledge
  base doesn't have. Revisit only if a future knowledge-base domain has genuinely long chapters.

### P4 (do not port)

- **Multi-format RAG loaders** (pdf/docx/csv/xlsx/sqlite ingestion): `routing_lab2/` deliberately
  routes CSV/JSON data through dedicated tools (`sql_query`, `metadata_lookup`) instead of RAG -
  blurring that boundary to match `rag_krish`'s do-everything loader would undo a real design
  decision, not fix a gap (see [routing-project-learnings.md §6](./routing-project-learnings.md)).
- **LLM-as-judge evaluation**: already discussed and deliberately rejected in
  [routing-project-learnings.md §7](./routing-project-learnings.md) - `routing_lab2/`'s
  deterministic metrics are the correct choice for measuring routing/retrieval accuracy
  specifically, which is this project's stated goal.
- **Config allow-list validation pattern**: genuinely good practice, but only worth adding *when*
  `retrieval_mode`/`splitter_type`-style knobs actually become constructor/CLI parameters (i.e.,
  as a natural side effect of doing P1, not as a standalone change).

---

## 5. Suggested execution order for `feature/routing-lab2`

1. ✅ `app/rag/reranking.py` + hybrid-mode `retrieve()` (P1, additive, default unchanged).
2. ✅ `scripts/compare_retrieval_modes.py` (P1's validation harness) - run it, record the result
   (positive or negative) in the README the same way past findings are recorded.
3. ✅ Step 2 showed **no win** (see §7) - default `retrieval_mode` left as `"similarity"`;
   confirmed the full Level 4/6 pytest suite (and, further, the *entire* 10-level suite
   end-to-end) is unaffected under hybrid/hybrid+rerank - see §7.
4. ✅ `app/rag/manifest.py` + incremental `build_index.py` (P2), done independently of 1-3 -
   validated with the no-op-on-rerun test plus the existing Level 4/6 suites (see §7).
5. ✅ P3/P4 skipped for this branch, as planned; this document (plus §7's addendum) remains the
   record of why.

Additionally, a **second, unplanned round of fixes** was done in a later session after re-reading
a different self-review document (`routing-project-learnings.md`, not `rag-krish-learnings.md`) -
see §7.2. This plan never anticipated that round, since it was scoped specifically to `rag_krish`
patterns.

---

## 6. Pre-merge validation checklist

- [x] `pytest routing_lab2/tests/test_rag_retrieval.py` (Level 4) still 100% / all passing
- [x] `pytest routing_lab2/tests/test_multichapter_evidence.py` (Level 6) still fully covered
- [x] `python scripts/compare_retrieval_modes.py` output recorded (see §7.1 - negative result)
- [x] `build_index.py` rerun twice back-to-back with no content changes confirmed a true no-op;
      editing one chapter and rerunning confirmed only that chapter's chunks were replaced (see §7.1)
- [ ] `python scripts/run_batch_tests.py` (full batch) vs.
      [outputs/batch_results.csv](../../routing_lab2/outputs/batch_results.csv) baseline - **not
      run**; the full 10-level pytest suite was run instead (409/410 passed, both under default
      and under hybrid/hybrid+rerank overrides - see §7.1), which exercises the same end-to-end
      graph paths `run_batch_tests.py` would. Worth running `run_batch_tests.py` too before merging
      to `main`, for its latency/token/cost reporting specifically.

---

## 7. What was actually implemented, found, and decided

### 7.1 P1 (hybrid retrieval + reranking) and P2 (incremental indexing) - as planned above

Implemented almost exactly as designed in §4, with the Chroma-specific adaptations already
anticipated (per-(topic, subtopic)-scoped BM25, skip the FAISS-only rename/vector-reuse trick).
Full details and code are in `routing_lab2/app/rag/retrieval.py`, `reranking.py`, `manifest.py`,
and `scripts/build_index.py`/`compare_retrieval_modes.py`.

**Benchmark result** (`scripts/compare_retrieval_modes.py`, 22 L4 + 23 L6 questions):

| Mode | L4 Recall@K | L6 Full Coverage | Avg latency |
|---|---|---|---|
| similarity | 100% | 100% | ~12ms |
| hybrid | 100% | 100% | ~8ms |
| hybrid+rerank | 100% | 100% | ~450ms |

**No measurable improvement from either technique** - exactly the outcome §1's evidence-based
reasoning predicted. **Decision: kept `similarity` as the default** (`app/config.py`'s
`RETRIEVAL_MODE`/`RERANK_ENABLED`); both modes are fully implemented, tested, and available on
demand (explicit `retrieve(..., retrieval_mode="hybrid", use_reranking=True)` params, or
`ROUTING_LAB_RETRIEVAL_MODE`/`ROUTING_LAB_RERANK_ENABLED` env vars), not defaulted-to without
evidence. Recorded in `routing_lab2/README.md`'s "Experiment: comparing retrieval modes" section,
with raw results in `routing_lab2/experiments/retrieval_mode_comparison.json`.

**Validation went further than this plan's checklist asked for**: beyond the Level 4/6
retrieval-only metrics above, the *entire* 10-level pytest suite was also run end-to-end with
`ROUTING_LAB_RETRIEVAL_MODE=hybrid` set (409/410 passed, identical to the `similarity` baseline),
and Levels 4/6 specifically with hybrid+rerank both enabled (91/91 passed) - confirming no
downstream generation/citation regression, not just unchanged retrieval metrics.

Incremental indexing (P2) was verified directly: a fresh run with no manifest did a full rebuild
matching the documented 57 chapters → 68 chunks baseline exactly; an immediate rerun was a true
no-op; editing one chapter's content and rerunning replaced only that chapter's chunks (3→4);
reverting and rerunning restored the original 3 chunks with zero diff against the original file.

### 7.2 Second round: fixes from `routing-project-learnings.md` (not part of this plan)

In a later session, the user asked to check the *other* learnings docs (not just
`rag-krish-learnings.md`) for further improvements. That surfaced three concrete, low-risk items
from [routing-project-learnings.md §11](./routing-project-learnings.md) that this document never
covered, since it was scoped specifically to `rag_krish`-derived RAG patterns:

- **`scripts/run_evaluations.py` genuinely crashed with `KeyError` on Level 6+** (confirmed by
  reproducing it before fixing), despite its own "all levels" usage text - rewritten to dispatch
  on the exact level number and reuse each level's own metric classes
  (`RetrievalResult`/`ClarificationResult`/`MultiChapterRetrievalResult`/`ToolSelectionResult`/
  `MultiHopResult`/`RecoveryResult`/`AnswerResult`). Verified: all 228 ground-truth questions now
  run through it without error, and its reported numbers match this project's documented results
  exactly (including surfacing the same pre-existing `L3-022` flake).
- **`app/tools/sql_query.py` now rejects non-`SELECT`/`WITH` queries** (and forbidden keywords)
  before executing LLM-generated SQL - cheap defense-in-depth, verified against a direct `DROP
  TABLE` and a chained `SELECT; DELETE` attempt, with all Level 8/10 tests still passing.
- **`app/agents/synthesis_agent.py`'s multi-topic synthesis prompt now explicitly preserves
  `tool:<name>` citations**, matching what `multihop_agent.py`'s synthesis prompt already did.

Considered but explicitly **not** done (also from the same self-review, deliberately deferred,
not forgotten): `complexity_router`'s always-on-but-unbranched classification call - the
self-review itself frames this as "wire it up or remove it," and either change risks altering
behavior across all 228 calibrated ground-truth rows without a clear accuracy benefit to justify
the risk. Left for a dedicated follow-up with its own benchmark, same reasoning this document
already applied to P1/P2 above.

See commit `aa38803` for the full diff and verification details.
