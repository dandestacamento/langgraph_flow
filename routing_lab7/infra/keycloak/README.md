# Keycloak (local development only)

Self-hosted authentication/SSO, per
[`instructions/learnings/routing-lab-prod-plan.md`](../../../instructions/learnings/routing-lab-prod-plan.md)
section 2.1. Run from `routing_lab7/`:

```powershell
docker compose up -d
```

Then open http://localhost:8081 (admin console: `admin` / `admin`) or just use it directly - the
`routing-lab6` realm, its one public frontend client (`routing-lab6-frontend`), and two demo users
are imported automatically from [`realm-export.json`](./realm-export.json) on startup.

**Demo users** (for testing, including the `thread_id`-ownership check in
`app/api/main.py`/`app/api/auth.py` - log in as one, then try to access the other's conversation):

| Username | Password |
|---|---|
| `demo` | `demo-password` |
| `demo2` | `demo-password` |

## This is NOT a production configuration

`docker-compose.yml` runs Keycloak in Quarkus **dev mode** (`start-dev`): an ephemeral in-memory
H2 database (all realm/user data is lost on container restart - re-imported fresh from
`realm-export.json` each time, which is the point for local dev/testing) and HTTPS disabled
(`sslRequired: none`). Per `routing-lab-prod-plan.md` section 2.1/7, a real deployment needs:

- A persistent database (Keycloak supports Postgres - the same engine already used elsewhere in
  this plan) instead of the ephemeral dev-mode H2 store.
- `start --optimized` (the production Quarkus build mode), not `start-dev`.
- HTTPS enforced (`sslRequired: external` at minimum), proper hostname configuration, and running
  behind the project's chosen ingress (NGINX/Traefik, per section 7).
- Real admin credentials and demo-user passwords removed/replaced - the ones in
  `realm-export.json` are throwaway values for local testing, committed to git on purpose (there
  is nothing sensitive about them), and must never be reused anywhere real.
- `redirectUris`/`webOrigins` scoped to the actual production frontend origin(s), not
  `localhost`.
