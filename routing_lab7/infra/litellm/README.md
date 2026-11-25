# LiteLLM (local development only)

Self-hosted LLM gateway providing per-user virtual API keys, budgets, and rate limits, per
[`instructions/learnings/routing-lab-prod-plan.md`](../../../instructions/learnings/routing-lab-prod-plan.md)
section 2.3. Run from `routing_lab7/`:

```powershell
docker compose up -d litellm
```

This requires `OPENAI_API_KEY` to be set in the repo-root `.env` (the same one this project
already reuses - see `routing_lab7/README.md`'s "VS Code setup") - `docker-compose.yml`'s
`litellm` service reads it from there via `env_file: ../.env`.

`app/llm_gateway.py` is the one place in the app that knows about this proxy: every
`ChatOpenAI`/`OpenAIEmbeddings` call site (16 of them, across `app/routers/`, `app/agents/`,
`app/chat/condense.py`, `app/architectures/_shared.py`, `app/rag/embeddings.py`) spreads
`**llm_gateway.llm_kwargs()` into its constructor, which is a no-op (empty dict) unless
`LITELLM_BASE_URL` is set - so nothing changes for anyone running this project without LiteLLM.

`app/api/main.py` provisions one LiteLLM virtual key per authenticated user (via `/key/generate`,
using the master key) the first time it sees their Keycloak `sub`, with a small demo budget - see
`UserKeyProvisioner` in `app/llm_gateway.py`. The provisioned key is cached (persisted in Postgres
when `CHAT_DB_URL` is set, in-memory otherwise, the same pattern as `ThreadOwnershipRegistry`) and
used for every one of that user's LLM calls via a per-request `contextvars.ContextVar` - not a
process-global env var, which would race across concurrent users' requests.

## This is NOT a production configuration

- `DATABASE_URL` points at its own dedicated `litellm` database within the same Postgres instance
  `app/api/main.py`'s `PostgresSaver`/`thread_owners` table use - **not** the same database
  (`routing_lab7_chat`). LiteLLM's Prisma-managed migration tooling refuses to share a database
  that already has unrelated tables in it (a real conflict hit while validating this phase, not a
  hypothetical one) - see `infra/postgres/init-litellm-db.sql`.
- `LITELLM_MASTER_KEY`/`LITELLM_SALT_KEY` below are throwaway dev values, committed to git on
  purpose (nothing sensitive about them) - replace both with real secrets (ideally sourced from
  OpenBao, per `routing-lab-prod-plan.md` section 2.4) before any real deployment. `LITELLM_SALT_KEY`
  specifically cannot be changed later without losing access to any already-stored provider
  credentials, so a real deployment must pick its real value up front.
- The per-user demo budget in `UserKeyProvisioner` is deliberately tiny (enough to demonstrate a
  real budget-exceeded rejection quickly) - a real deployment needs an actual, product-informed
  budget policy, not this demo value.
