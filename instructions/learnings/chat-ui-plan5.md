# Status & decisions (recorded 2026-11-18, branch `feature/chat-ui-plan5`, in `routing_lab5/`)

This document below is external advice. This header records what was actually built and the
v1 trims, so the advice isn't re-litigated later.

## Phase A - DONE (local upload → classify → index → validate → publish)

- **Separate ingestion LangGraph workflow** (`app/ingestion/graph.py`):
  validate → extract → classify → chunk → index → validate_retrieval → publish, with
  conditional terminal routes to `failed` / `needs_review`, per-node timed events recorded in
  the registry (the future Ingestion Inspector's raw material), and a retrieval-validation
  rollback (unfindable documents are de-indexed, never published). The QA graph is untouched.
- **Document registry** (`app/ingestion/registry.py`): dual-mode Postgres/in-memory;
  content-hash dedup, status lifecycle (processing/indexed/needs_review/failed), chunk-id
  bookkeeping for surgical later deletes, event log. **Storage adapter**
  (`app/ingestion/storage.py`): immutable originals under gitignored
  `data/documents/<id>/v<n>/` - the local implementation of the plan's adapter interface.
- **Classification** (`app/ingestion/classify.py`): one structured-output call into the existing
  `TOPIC_SUBTOPICS` taxonomy + free chapter labels; confidence used as a routing signal only
  (plan's own caveat); off-taxonomy or <0.6 confidence → `needs_review` (parked, visible,
  not indexed - the human-review UI is Phase C). Document text framed as untrusted data.
- **API** (`app/api/main.py`): `POST /knowledge/documents` (sniffed types: PDF + UTF-8 text
  family; 5 MB cap; dedup returns the existing document with `duplicate: true`; processing runs
  as a background task so uploads never block chat), `GET /knowledge/documents[/{id}]`.
- **Chunks land in the SAME Chroma collection** with the retriever's exact metadata keys plus
  provenance (`document_id`, `source`, `version`, `ingested`) - so retrieval, citations and the
  router work on ingested knowledge with zero QA-side changes. Proven by the Phase A exit test:
  a WM-500 bulletin introducing fault code E77 (absent from the curated KB) was uploaded, and
  the unchanged `/chat` answered "What does washing machine error E77 mean?" citing it.
- Tests: 8 new (`tests/test_ingestion.py`) incl. that end-to-end, dedup, off-taxonomy parking,
  honest unreadable-PDF failure; the existing 41 chat/condensing tests stay green.

## v1 trims (deliberate, consistent with earlier plans' rejections)

- **No Celery/Redis** - FastAPI background tasks + registry status until cloud adapters need a
  real queue. **No Docling/Unstructured** - plan4's extractors (pypdf + text family) cover v1;
  DOCX later. **No Next.js** - the Knowledge Base Manager (Phase B) joins the existing Vite app.
- Known caveats, documented in `app/ingestion/graph.py`: `build_index.py --rebuild` wipes
  ingested chunks (re-publish/reindex action is Phase C); hybrid-mode BM25 picks up new content
  only after a restart (default similarity mode is immediate).

## Remaining phases

Phase B: Knowledge Base Manager UI (upload, job list, document detail, manual override).
Phase C: human review/resume, update/versioning/deletion, reindex action.
Phase D: watchdog inbox, MLflow tracing + Ingestion Inspector, Azure Blob / S3 event adapters.

---

I recommend adding an Automated RAG Knowledge Ingestion Pipeline to your langgraph_routing application.

This would be an excellent next feature because you can demonstrate not only LangGraph's question-routing capabilities but also how an AI application automatically discovers, classifies, processes, and indexes new knowledge.

The ideal process is:

Upload file → Detect new document → AI classifies topic → Extract content → Validate → Chunk → Generate embeddings → Store in topic-specific RAG index → Test retrieval → Make searchable.

I would support three ingestion methods: upload through your application's UI, upload to Azure Blob Storage or AWS S3, and drop files into a monitored local folder.
1. Proposed end-to-end architecture
Document Sources

Web UI · Local folder · Azure Blob · AWS S3


Ingestion Event Queue

New file detected · Deduplication · Job created


LangGraph Ingestion Workflow

Extract → Classify → Validate → Chunk → Embed


Appliances

Refrigerators · Washers


Azure

Networking · Security


Data Engineering

Spark · Databricks




Index Verification and Publication

Check retrieval, citations, versions and permissions


Available to RAG Chat

Topic Router → Retriever → Answer with sources


The key architectural point is that document ingestion and question answering should be separate LangGraph workflows. Uploading documents should not interrupt active customer conversations.
2. How each upload method works
Source	How to detect new files	Recommended implementation
Chat UI	User uploads through the browser	FastAPI upload endpoint
Local filesystem	File created or modified	Python watchdog
Azure Blob Storage	Blob-created event	Azure Event Grid → Queue/Function
AWS S3	Object-created event	S3 Event Notifications → SQS/Lambda

All four should send a standardized ingestion job into the same processing pipeline.

For example:
{
  "event_type": "document_uploaded",
  "document_id": "DOC-1045",
  "source": "azure_blob",
  "file_path": "appliances/washing_machines/wm500_manual.pdf",
  "status": "queued"
}


The worker retrieves the actual file from its source and processes it. Use the storage object's version, ETag or content hash to detect duplicates and updates.
3. Suggested upload UI
I would add a Knowledge Base section to your existing ChatGPT-style application.
Knowledge Base Manager

Manage documents and RAG indexes


Upload knowledge documents

PDF, Markdown, TXT, DOCX, CSV, JSON

Drag and drop or select files

Topic assignment
Automatic AI classification

Manually select topic and subtopic



Recent ingestion jobs
Document	Assigned topic	Status
washer_manual.pdf	Appliances	Indexed
azure_networking.md	Azure	Review
spark_optimization.pdf	Data Engineering	Processing

Illustrative interface and statuses, not live upload functionality.
I would also provide a document details screen showing classification confidence, extracted text, chunk count, embedding model, indexed version, and retrieval test results.
4. Use LangGraph to classify new documents automatically
This is where your application becomes more interesting.

Suppose a user uploads Samsung_WM500_User_Manual.pdf.

Your LangGraph ingestion workflow could follow these steps:
Step	Node	Action
1	File Validator	Check file type, size, integrity and safety
2	Content Extractor	Extract text, tables and document structure
3	Topic Classifier	Identify Appliances
4	Subtopic Classifier	Identify Washing Machines
5	Chapter Classifier	Identify Troubleshooting, Operation, Warranty
6	Confidence Evaluator	Determine whether classification requires review
7	Chunking Agent	Split content by headings, sections and chapters
8	Embedding Node	Generate embeddings
9	Vector Store Writer	Insert chunks with topic and chapter metadata
10	Retrieval Validator	Test whether the new content can be found
11	Publisher	Make the document available to RAG queries

A document can belong to multiple chapters or subtopics. Don't force the entire manual into one category.
Example classification result
{
  "document_id": "DOC-1045",
  "filename": "Samsung_WM500_User_Manual.pdf",
  "topic": "appliances",
  "subtopic": "washing_machines",
  "chapters": [
    "operation",
    "troubleshooting",
    "warranty"
  ],
  "classification_confidence": 0.97,
  "status": "ready_for_indexing"
}


The confidence value above is illustrative. In the real application, use it as a routing signal rather than treating an LLM's self-reported confidence as a calibrated probability.

For ambiguous documents, the graph should pause for human review using LangGraph interrupts.
5. How to organize the RAG indexes
You have two choices.
Architecture	Advantages	Disadvantages
Separate vector collection per topic	Strong isolation, easy topic-specific search	Harder to search across topics
Shared collection with metadata filters	Easier cross-topic search, simpler management	Requires careful metadata and access filtering

I recommend starting with one Chroma collection using metadata filters.

For example, every chunk could contain:
{
  "document_id": "DOC-1045",
  "topic": "appliances",
  "subtopic": "washing_machines",
  "chapter": "troubleshooting",
  "section": "error_codes",
  "source": "Samsung_WM500_User_Manual.pdf",
  "version": "1.0",
  "chunk_id": "DOC-1045-CH03-001"
}


When someone asks, "What does washing machine error E21 mean?", the query router can search the washing-machine troubleshooting content first.

If the query involves multiple topics, it can retrieve across multiple metadata filters or perform a broader search.

Keep document access permissions separate from topic classification so users cannot retrieve content they are not authorized to view.
6. Handle document updates, duplicates and deletions
This is essential for a production-style application.
Event	Expected behavior
New document	Extract, classify, index and publish
Same file uploaded again	Detect duplicate; avoid unnecessary reindexing
Updated document	Build new version, verify, then replace active index entries
Deleted document	Remove or deactivate associated chunks
Failed extraction	Record error and send to retry/review queue
Classification uncertain	Request human approval
Conflicting information	Flag conflicting sources for review
Unsupported file	Reject safely with an explanation

Use a document registry in SQLite or PostgreSQL to track file versions, processing status, source locations, hashes, and associated vector chunk IDs.

For updates, I recommend indexing the replacement version before activating it, so an ingestion failure does not immediately remove working knowledge.

Also protect the pipeline against malicious files and prompt-injection instructions embedded in uploaded documents. Treat document text as untrusted source material, not instructions to the agent.
7. Add automated retrieval tests after ingestion
This is especially relevant to your routing accuracy project.

After indexing a new document, run a few targeted retrieval tests before publishing it.

For example, after uploading a washing machine manual:
Test question	Expected result
What does error E21 mean?	Retrieve error-code section
How do I clean the drain filter?	Retrieve maintenance section
What is the motor warranty?	Retrieve warranty section
What is Azure VNet peering?	Do not route to appliance content

You can also run your existing 20-question benchmark after ingestion to detect regressions.

The pipeline should distinguish retrieval success from answer correctness. Finding the right document does not automatically mean the generated answer is accurate.
8. Recommended technology stack
Component	Recommended technology
Upload UI	React / Next.js
API	FastAPI
Ingestion orchestration	LangGraph
Background jobs	Celery + Redis, or a managed queue
Local folder monitoring	Python watchdog
Azure events	Event Grid + Azure Functions / Queue
AWS events	S3 Events + SQS / Lambda
Document extraction	Docling or Unstructured
Vector database	Chroma initially
Document registry	SQLite initially, PostgreSQL later
Observability	MLflow
Evaluation	pytest + your batch routing test runner

For your first implementation, use the local filesystem and UI upload. Once the workflow is reliable, add Azure Blob and S3 adapters without rewriting the ingestion graph.
9. Copilot prompt to implement this feature
Implement Automated RAG Knowledge Ingestion
Extend my existing langgraph_routing application with an automated document ingestion pipeline.

The application currently uses LangGraph, RAG, FastAPI and a chat UI.

Do not replace my existing question-answering graph. Create a separate LangGraph workflow for document ingestion.
Requirements
1. Add a Knowledge Base Manager page to the UI.
2. Allow uploading PDF, Markdown, TXT, DOCX, CSV and JSON files.
3. Support automatic AI classification into existing topics, subtopics and chapters.
4. Allow manual classification overrides.
5. Store uploaded files in a local staging directory.
6. Create an ingestion job for each uploaded file.
7. Process jobs asynchronously so uploads do not block the chat application.
8. Implement LangGraph nodes for:
   - File validation
   - Content extraction
   - Topic classification
   - Subtopic classification
   - Chapter/section classification
   - Confidence evaluation
   - Human review
   - Chunking
   - Embedding generation
   - Vector database indexing
   - Retrieval validation
   - Publication
9. Preserve document metadata and source references for citations.
10. Support multi-topic and multi-chapter classification.
11. Use Chroma metadata filtering for topic-specific retrieval.
12. Detect duplicates using file hashes.
13. Support document updates, versioning and deletion.
14. Handle ingestion failures with retries and error reporting.
15. Use LangGraph checkpointing for resumable workflows and human approval.
16. Treat uploaded document content as untrusted data and enforce document access permissions.
17. Display ingestion status, classification results, extracted chapters, chunk counts and errors in the UI.
18. Add MLflow tracing for the ingestion workflow.
19. After indexing, run retrieval validation tests.
20. Integrate the new knowledge with my existing LangGraph question router.
Storage adapters
Implement a common storage interface supporting:
- Local filesystem
- Azure Blob Storage
- AWS S3
Start with local filesystem and UI upload. Add Azure Blob and S3 event-driven adapters after the local workflow passes tests.
Testing
Create tests covering:
- Correct topic and subtopic classification
- Multi-topic documents
- Duplicate uploads
- Updated documents
- Failed extraction
- Uncertain classification
- Human review and resume
- Successful indexing
- Retrieval after ingestion
- Deletion and reindexing
- Cross-topic routing
- Prompt-injection resistance
Observability
Display the actual ingestion graph execution path using Mermaid and MLflow.

Record each node, decision, state transition, duration, tool call, and failure.

Do not fabricate execution results or accuracy metrics.
Implementation plan
First inspect the existing project and reuse its current models, RAG components, and vector database.

Implement the local upload workflow first.

Run automated tests before adding cloud storage integrations.

Keep the implementation modular and production-oriented.




10. My suggested development sequence
1

UI upload + local ingestion

Upload a Markdown or PDF file, classify it, and index it automatically.


2

Classification and human review

Add topic confidence checks, multiple chapter assignments and manual corrections.


3

RAG validation and testing

Verify retrieval, citations and accuracy against your ground-truth questions.


4

Cloud storage ingestion

Add Azure Blob and AWS S3 event listeners using the same ingestion workflow.


5

Production reliability

Add versioning, deletion, queues, retries, permissions and monitoring.



One additional feature I strongly recommend: Add an Ingestion Inspector beside your existing LangGraph Routing Inspector. This would let you examine the complete document lifecycle, from upload through classification, chunking, embeddings, indexing and retrieval verification.

That gives your application two complementary capabilities: automated knowledge ingestion and observable, accuracy-tested question answering. Together, they make a much stronger demonstration of LangGraph and enterprise RAG architecture.