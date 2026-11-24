# Starting the routing-lab chat UI by hand

How to bring up the full stack (auth + database + backend + frontend) from a cold
machine, e.g. after a reboot. All commands are **PowerShell** — open "Windows
PowerShell" or "Terminal", NOT "Command Prompt" (`$env:...` syntax fails in cmd
with "The filename, directory, or volume label syntax is incorrect"). Run from
the repo root (`langgraph_flow\`).

## What runs where

| Piece | Port | How it runs |
| --- | --- | --- |
| Keycloak (login) | 8081 | Docker, `routing_lab6/docker-compose.yml` |
| Postgres (threads + knowledge registry) | 5433 | Docker, same compose file |
| LiteLLM proxy | 4000 | Docker, same compose file |
| FastAPI backend | 8000 | local `uvicorn`, repo-root `.venv` |
| Vite dev server (the UI) | 5173 | local `npm run dev` |

**Run only ONE lab at a time.** `routing_lab3`, `routing_lab5` and `routing_lab6`
all want ports 8000/5173, and the Keycloak
dev realm only allows `http://localhost:5173` as a login redirect. The commands below
use `routing_lab6` and its own Docker stack, chat database and vector index.

## One-time prerequisites (already done on this machine)

- Repo-root `.env` containing `OPENAI_API_KEY=...` (see `routing_lab6\.env.example`;
  the labs read the shared repo-root `.env`, not their own).
- Python deps in the shared repo-root venv: `.venv\Scripts\python.exe` exists.
- Frontend deps: `cd routing_lab6\frontend; npm ci`
- Vector index: `routing_lab6\.chroma\manifest.json` exists. If missing, build it once with
  `cd routing_lab6; ..\.venv\Scripts\python.exe scripts\build_index.py`
  (⚠ never use `--rebuild` casually — it wipes ALL chunks including ingested
  documents; re-ingest or wait for the Phase C reindex action).

The new lab6 database starts empty: lab5 conversations and uploaded document
records are not automatically copied. Re-upload documents you need in lab6.
Building the curated index does not index copied files under `data\documents`.

## Startup, in order

### 1. Docker Desktop

Must be running first. If `docker info` fails, start it and wait (~30-60 s):

```powershell
Start-Process "$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe"
```

### 2. Keycloak + Postgres + LiteLLM

```powershell
cd routing_lab6
docker compose up -d
```

Wait until Keycloak answers (first boot of the container takes ~20-40 s):

```powershell
curl.exe -s -o NUL -w "%{http_code}" http://localhost:8081/realms/routing-lab6   # want 200
```

The lab6 Compose stack creates its database automatically on first startup.

### 3. Backend (keep this window open)

```powershell
cd routing_lab6
$env:CHAT_DB_URL = "postgresql://routing_lab6:routing-lab6-dev-password@localhost:5433/routing_lab6_chat"
..\.venv\Scripts\python.exe -m uvicorn app.api.main:app --port 8000
```

`CHAT_DB_URL` makes conversations and the knowledge-document registry persist in
Postgres. Omit it and everything still works, but in memory only (lost on restart).

If you must use Command Prompt (cmd.exe) instead of PowerShell, set the variable
with cmd syntax — no `$env:`, no quotes:

```cmd
set CHAT_DB_URL=postgresql://routing_lab6:routing-lab6-dev-password@localhost:5433/routing_lab6_chat
```

### 4. Frontend (second window, keep open)

```powershell
cd routing_lab6\frontend
npm run dev
```

### 5. Log in

Open http://localhost:5173 — you'll be redirected to Keycloak.
Dev credentials: **demo / demo-password**.

## Testing uploaded documents and answer support

Knowledge-base uploads index the complete extracted text, split into bounded
chunks; PDF passages record page numbers. The 5 MB upload limit still applies.
Scanned/image-only pages need OCR and are rejected; images embedded alongside
text are not interpreted. Existing lab5 uploads must be uploaded again to get
the new chunks and page metadata.

Run a batch normally, or opt in to an approximate LLM evidence-support judgment:

```powershell
cd routing_lab6
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
- `cd routing_lab6; docker compose stop` (or `down`). **Never `down -v`** unless you
  want to wipe Keycloak users and all stored conversations/registry rows — recreating
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
