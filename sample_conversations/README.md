# Sample conversations for the routing_lab3 chat app

Scripted walkthroughs of what the app is expected to do, with and without file uploads.
Every expected answer below was actually observed against the real stack while the
features were built (chat-ui-plan1 through plan4) - they are not aspirational.

## Before you start

1. Start the infrastructure and app from `routing_lab3/`:

   ```powershell
   cd routing_lab3
   docker compose up -d keycloak postgres
   $env:CHAT_DB_URL = "postgresql://routing_lab3:routing-lab3-dev-password@localhost:5433/routing_lab3_chat"
   ..\.venv\Scripts\python.exe -m uvicorn app.api.main:app --port 8000
   # in a second terminal:
   cd routing_lab3\frontend
   npm run dev
   ```

2. Open http://localhost:5173 and log in as `demo` / `demo-password`.
3. The files referenced by the scripts live in [`files/`](./files/).

## The scripts

| Script | What it demonstrates |
|---|---|
| [`01-knowledge-base-only.md`](./01-knowledge-base-only.md) | Plain chat: routing, citations, tools, multi-hop, follow-up memory, meta questions |
| [`02-image-attachments.md`](./02-image-attachments.md) | Uploading/pasting screenshots: vision-grounded KB answers vs. direct descriptions |
| [`03-document-attachments.md`](./03-document-attachments.md) | PDFs/Markdown/CSV/text: summaries, mixed attachment+KB questions, honest failure modes, prompt-injection resistance |

## General things to watch in every conversation

- The **sidebar title** becomes a short generated summary after the first turn (not your raw question).
- **▶ Routing details** under knowledge-base answers expands to the topic breadcrumb, the
  execution timeline (per-node timings), and clickable passage cards that open the full
  cited text in a side panel. Scores are L2 distances - **lower = closer match**.
- Answers from conversation memory or attachments show **no** Routing details - no routing
  ran, so no fake citations.
- Refresh the page at any point: the conversation, its citations, and attachment
  thumbnails all restore from the server.
