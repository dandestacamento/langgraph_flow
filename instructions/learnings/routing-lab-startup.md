# Starting the routing-lab7 chat UI by hand

How to bring up the full stack (auth + database + backend + frontend) from a cold
machine, e.g. after a reboot. All commands are **PowerShell** — open "Windows
PowerShell" or "Terminal", NOT "Command Prompt" (`$env:...` syntax fails in cmd
with "The filename, directory, or volume label syntax is incorrect"). Run from
the repo root (`langgraph_flow\`).

## What runs where

| Piece | Port | How it runs |
| --- | --- | --- |
| Keycloak (login) | 8082 | Docker, `routing_lab7/docker-compose.yml` |
| Postgres (threads + knowledge registry) | 5434 | Docker, same compose file |
| LiteLLM proxy | 4001 | Docker, same compose file |
| FastAPI backend | 8000 | local `uvicorn`, repo-root `.venv` |
| Vite dev server (the UI) | 5173 | local `npm run dev` |

**Run only ONE lab at a time.** `routing_lab3`, `routing_lab5`, `routing_lab6`
and `routing_lab7` all want ports 8000/5173. The commands below use
`routing_lab7` and its Docker stack, chat database and vector index.

## One-time prerequisites

- Repo-root `.env` containing `OPENAI_API_KEY=...` (see `routing_lab7\.env.example`;
  the labs read the shared repo-root `.env`, not their own).
- Python deps in the shared repo-root venv: `.venv\Scripts\python.exe` exists.
- Frontend deps: from the repo root, `cd routing_lab7\frontend; npm ci`.
- Vector index: `routing_lab7\.chroma\manifest.json` exists. If missing, build it once
  from the repo root with `cd routing_lab7; ..\.venv\Scripts\python.exe scripts\build_index.py`
  (⚠ never use `--rebuild` casually — it wipes ALL chunks including ingested
  documents). Building the index can incur embedding costs.

A newly initialized lab7 database starts empty: conversations and uploaded
document records from other labs are not automatically copied. Re-upload
documents you need in lab7. Building the curated index does not index copied
files under `data\documents`.

An existing lab7 PostgreSQL volume may instead contain the copied lab6 role
and database names; Compose environment changes do not rename them. Back up
the volume and follow the migration instructions in the
[lab7 README](../../routing_lab7/README.md#chat-application) if applicable.
Do not delete the volume to resolve a startup problem.

## Startup, in order

### 1. Docker Desktop

Must be running first. If `docker info` fails, start it and wait (~30-60 s):

```powershell
Start-Process "$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe"
```

### 2. Keycloak + Postgres + LiteLLM

```powershell
cd routing_lab7
docker compose up -d
```

Wait until Keycloak answers (first boot of the container takes ~20-40 s):

```powershell
curl.exe -s -o NUL -w "%{http_code}" http://localhost:8082/realms/routing-lab6   # want 200
```

The lab7 stack still uses the `routing-lab6` Keycloak realm and client names.
This is intentional in the current configuration; do not rename them in the
URL. A new Compose volume initializes the lab7 database on first startup.

### 3. Backend (keep this window open)

Open a new PowerShell window at the repo root:

```powershell
cd routing_lab7
$env:CHAT_DB_URL = "postgresql://routing_lab7:routing-lab7-dev-password@localhost:5434/routing_lab7_chat"
..\.venv\Scripts\python.exe -m uvicorn app.api.main:app --port 8000
```

`CHAT_DB_URL` makes conversations and the knowledge-document registry persist in
Postgres. Omit it and everything still works, but in memory only (lost on restart).
These backend commands use the provider directly unless LiteLLM is configured
separately; starting its container alone does not enable per-user budgets.
See the [LiteLLM guide](../../routing_lab7/infra/litellm/README.md).

If you must use Command Prompt (cmd.exe) instead of PowerShell, set the variable
with cmd syntax — no `$env:`, no quotes:

```cmd
set CHAT_DB_URL=postgresql://routing_lab7:routing-lab7-dev-password@localhost:5434/routing_lab7_chat
```

### 4. Frontend (second window, keep open)

Open another PowerShell window at the repo root:

```powershell
cd routing_lab7\frontend
npm run dev
```

### 5. Log in

Open http://localhost:5173 — you'll be redirected to Keycloak.
Dev credentials: **demo / demo-password**.

## Testing uploaded documents and answer support

Knowledge-base uploads index the complete extracted text, split into bounded
chunks; PDF passages record page numbers. The 5 MB upload limit still applies.
Scanned/image-only pages need OCR and are rejected; images embedded alongside
text are not interpreted. Previously uploaded documents may need to be
re-indexed to get the new chunks and page metadata; see the
[lab7 README](../../routing_lab7/README.md).

For step-by-step manual regression, use the
[lab7 manual Q&A guide](../../routing_lab7/docs/manual_regression_q_and_a_20261126.md).
The underlying question sets are
[batch_test_questions.json](../../routing_lab7/datasets/batch_test_questions.json),
[nist_questions.json](../../routing_lab7/datasets/nist_questions.json), or
[dishwasher_manual_file2_questions.json](../../routing_lab7/datasets/dishwasher_manual_file2_questions.json).
Ask the questions in the chat UI, compare each response with the guide's
expectation, and inspect **Routing details** and the source passages. NIST and dishwasher manual
questions require the corresponding document to be indexed. Record your verdict
and comments in your own notes or the appropriate `manual_review.csv` under
`routing_lab7\outputs`. Retrieved sources do not guarantee that an answer is
supported; check the actual passage.

For an optional automated batch and approximate LLM evidence-support judgment,
run from the repo root:

```powershell
cd routing_lab7
..\.venv\Scripts\python.exe scripts\run_batch_tests.py --ids T001 --llm-judge
```

The judge sends the question, answer and retrieved evidence to the configured
model provider and incurs extra calls. Its verdict and explanation are in
`batch_details.json` and `batch_report.md`, separate from deterministic
pass/fail. It is not proof of correctness; review uncertain/unsupported results.
Batch token/cost totals do not include judge calls. Cases without recorded
evidence are marked not evaluated.

## Shutting down

- `Ctrl+C` in the uvicorn and Vite windows.
- From the repo root, `cd routing_lab7; docker compose stop` (or `down`).
  **Never `down -v`** unless you want to wipe stored conversations/registry rows — recreating
  the Keycloak container regenerates user ids, orphaning existing threads anyway
  (see troubleshooting).

## Troubleshooting

- **Conversation history cannot load** — check `http://localhost:8000/health`.
  If it is unreachable, start the backend in step 3 and use Retry in the UI.
- **Login loop / "session expired"** — the dev realm idles sessions out after
  ~30-60 min; just log in again as demo/demo-password.
- **Sidebar suddenly empty after recreating containers** — Keycloak dev-mode gives
  users new internal ids when its container is recreated (not merely restarted), so
  old threads belong to the "old" demo user and won't show. They're still in
  Postgres, just orphaned.
- **Port already in use on 8000/5173** — the other lab (or a previous run) is still
  up; stop it first. `Get-NetTCPConnection -LocalPort 5173 | Select OwningProcess`
  finds the PID.
- **Chat can't find newly ingested documents in hybrid retrieval mode** — the BM25
  retriever is cached per-process; restart the backend. Default similarity mode
  picks new content up immediately.
- **MLflow tracing (optional, off by default)** — only if you're actively testing:
  run `start_mlflow.ps1` from the repo root first, then start the backend. If the
  tracking server is unreachable, tracing is skipped automatically; nothing else
  needs it running.
