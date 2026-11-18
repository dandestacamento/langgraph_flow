-- Runs once, only on a brand-new (empty) Postgres data volume - the
-- official postgres image executes every *.sql file in
-- /docker-entrypoint-initdb.d/ on first container startup, never again
-- afterward (see docker-compose.yml's postgres service). Creates a
-- second, separate database for LiteLLM (infra/litellm/) - its own
-- Prisma-managed migration tooling refuses to share a database that
-- already has unrelated tables in it (this project's own `checkpoints`/
-- `thread_owners`), a real conflict hit while validating this phase.
CREATE DATABASE litellm OWNER routing_lab3;
