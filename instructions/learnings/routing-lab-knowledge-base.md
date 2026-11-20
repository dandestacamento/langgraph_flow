# Adding documents to the knowledge base (routing_lab5)

How to teach the assistant new facts by uploading documents through the
Knowledge Base Manager, what each status means, and how to verify the
content is actually being used in chat.

Prerequisite: the stack is running and you're logged in — see
`routing-lab-startup.md` in this folder. This feature exists in
**routing_lab5** only (branch `feature/chat-ui-plan5`).

## Adding a file through the UI

1. Click **Knowledge base** in the header (top right).
2. Drag a file onto the dashed upload zone, or click **browse**.
   Multiple files at once are fine.
3. The document appears in the list as **Processing** and settles within
   a few seconds — the list polls every 2 s while anything is in flight.
4. Click a row to expand it: classification + confidence, chunk count,
   and the **Pipeline log** (each ingestion step with its duration —
   validate → extract → classify → chunk → index → validate_retrieval →
   publish).

No restart is needed: as soon as a document shows **Indexed**, the chat
can answer from it (ask in a new conversation; see "Verifying" below).

## Supported files and limits

- **PDF** (must contain real text — a scanned/image-only PDF fails
  honestly with an "extracted 0 chars" error rather than indexing noise)
- **UTF-8 text family**: `.md`, `.txt`, `.csv`, `.json`, `.log`, etc.
- Max **5 MB** per file. Images are deliberately not accepted here —
  that's the chat attachment flow, not knowledge ingestion.
- The real file type is sniffed from the bytes; the filename/extension is
  never trusted.
- Uploading the **exact same bytes twice** is detected by content hash:
  you get the existing document back and nothing is reprocessed.

## What the statuses mean

| Status | Meaning | What to do |
| --- | --- | --- |
| Processing | Pipeline is running | Wait (a few seconds) |
| Indexed | Published; chat can cite it | Nothing — test it in chat |
| Needs review | Classifier was unsure (<60% confidence) or picked a topic/subtopic outside the taxonomy | Expand the row and use the override form |
| Failed | Validation/extraction failed (too large, unreadable PDF, …) | Expand the row to read the error; fix the file and re-upload |

A `needs_review` or `failed` document is **not** searchable by chat —
parked documents never pollute answers.

## Manual classification override

When a document is parked as **Needs review** (or **Failed**), expanding
its row shows a *"Classify this document manually to index it"* form:

1. Pick the correct **Topic** and **Subtopic** (the dropdowns are served
   by the backend, so they always match the live taxonomy).
2. Click **Reclassify & index**.
3. The pipeline re-runs from the stored original with your classification
   (no LLM call — confidence shows 100%) and the document becomes
   **Indexed**. The pipeline log keeps the full history, including a
   `manual_override` entry.

Current taxonomy (`routing_lab5/app/config.py` → `TOPIC_SUBTOPICS`):
appliances (refrigerators / washing_machines / dishwashers),
azure_cloud (networking / compute / security / storage),
data_engineering (spark / databricks / adf),
python (fundamentals / oop / concurrency),
finance (budgeting / loans / investments),
customer_support (orders / refunds / delivery).

## Verifying a document is used by chat

1. Click **Back to chat** → **+ New conversation**.
2. Ask about a fact that exists only in your document.
3. The answer should contain the fact, and the Sources line should include
   an `ingested_…` entry.
4. Expand **Routing details** → the ingested chunk should appear among the
   passage cards (usually with the lowest/best L2 score for a specific
   question); click it to see the full stored text and the document id.

## Sample files to try (in `instructions/sample_files/`)

| File | Expected outcome |
| --- | --- |
| `azure-vnet-flow-logs-update.md` | Auto-indexes under azure_cloud/networking. Ask: "How long can VNet flow log retention be set when storage is cross-region?" |
| `python-taskgroup-style-note.txt` | Auto-indexes under python/concurrency. Ask: "When is asyncio.gather still acceptable under our team style note?" |
| `fridge-fr200-models.csv` | Auto-indexes under appliances/refrigerators. Ask: "What is the capacity and price of the FR-200 Mini refrigerator?" |
| `spark-shuffle-tuning.pdf` | A real text-bearing PDF; auto-indexes under data_engineering/spark. Ask: "What size should each shuffle partition be according to the tuning notes?" |
| `pasta-recipes.md` | Nothing in the taxonomy fits → parked **Needs review** (low classifier confidence). Use it to practice the manual override (any topic you like — it's a demo). |
| `scanned-blank.pdf` | A PDF with no extractable text → **Failed** with an honest extraction error. |

All facts in these files are fictional and written so they cannot come
from the model's general knowledge — if the chat answers them correctly,
the answer provably came from your upload.

## Adding files from the command line (optional)

The UI calls these endpoints; you can script them with any bearer token
obtained from Keycloak:

- `POST /knowledge/documents` — multipart upload (field name `file`)
- `GET /knowledge/documents` — list all documents
- `GET /knowledge/documents/{id}` — one document incl. pipeline log
- `POST /knowledge/documents/{id}/classification` — body
  `{"topic": "...", "subtopic": "..."}` (422 if not in the taxonomy)
- `GET /knowledge/taxonomy` — the topic → subtopics map

## Caveats and current limitations

- **No delete/update yet** — removing or re-versioning a document is
  plan 5 Phase C. Until then a wrongly uploaded document can only be
  neutralised by cleaning the registry row + chunks manually.
- **`scripts/build_index.py --rebuild` wipes ingested chunks** along with
  the curated index. Avoid it; re-ingestion (or the Phase C reindex
  action) is the recovery path.
- **Hybrid retrieval mode caches BM25 per process** — if you switch the
  retriever to hybrid mode, restart the backend after ingesting. The
  default similarity mode sees new documents immediately.
- Documents are stored immutably under `routing_lab5/data/documents/`
  (gitignored) and registered in Postgres — both survive restarts. If you
  run the backend **without** `CHAT_DB_URL`, the registry is in-memory
  and the document list is empty after a restart even though chunks
  remain in the Chroma index.
- Document text is treated as **untrusted data** end to end — a document
  containing prompt-injection text gets indexed and quoted, not obeyed.
