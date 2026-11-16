# Full production-readiness plan (open source + enterprise-ready)

This is the production-hardening plan that was explicitly deferred in
[routing-lab3-chat-app-plan.md §8](./routing-lab3-chat-app-plan.md) ("production-ready: no, not
from this plan alone"). That document gets `routing_lab3/` to a working, open-source, self-hostable
**prototype** chat application; this document is what closes the gap to something genuinely
production-ready and enterprise-ready - **while staying fully open source throughout**, per the
explicit requirement this plan was commissioned under. Every component chosen below is checked
against its actual license, not assumed.

**Status**: plan only, nothing in this document is implemented yet. Being developed on its own
branch (`feature/routing-lab3`, branched from `feature/routing-lab2` so it carries forward that
branch's completed, tested P1/P2 work) since this is a major enough change to warrant isolation
from both `main` and the narrower `feature/routing-lab2` work.

**Deployment target (added after this plan was first drafted)**: the app will most likely deploy
as containers on Azure or AWS, using OpenAI (a paid, proprietary LLM API) rather than a
self-hosted model. Neither of these conflicts with the "fully open source" requirement - two
distinctions worth being explicit about, since they're easy to conflate:

- **The open-source requirement is about the application/tooling stack** (the agent framework,
  UI, auth, LLM gateway, observability, secrets management - §1's table) - it was never about the
  LLM provider itself. This project already uses OpenAI throughout (`ChatOpenAI`,
  `OpenAIEmbeddings`); nothing in this plan changes that. LiteLLM (§2.3) sits *in front of* OpenAI
  for budget/rate-limit enforcement - it doesn't replace it with anything self-hosted.
- **Running open-source software on a commercial cloud doesn't make it stop being open source.**
  Postgres run via Azure Database for PostgreSQL or AWS RDS is still the real, open-source Postgres
  engine underneath; Kubernetes run via AKS or EKS is still real Kubernetes. The cloud provider is
  an infrastructure/hosting decision, independent of - and compatible with - every software choice
  already made in §1. See the new §7 for the concrete Azure/AWS mapping.

---

## 0. A critical licensing finding that shapes this entire plan

Before anything else: **LangChain's official packaged LangGraph runtime is not fully open source
for production use**, and this plan is explicitly built to avoid it.

- The **LangGraph Python/JS library itself is MIT-licensed**, free, and self-hostable with zero
  restrictions - including its PostgreSQL checkpointer (`langgraph-checkpoint-postgres`), also
  MIT. Nothing about using `langgraph` as a library requires any LangChain service.
- The **packaged Agent Server** (published on PyPI as `langgraph-api` - what `langgraph up` runs,
  and what backs both local `langgraph dev` and LangChain's managed "LangSmith Deployment" /
  formerly-named "LangGraph Platform") is licensed under the **Elastic License 2.0**, and
  LangChain's own documentation states that running a standalone Agent Server **in production
  requires an Enterprise license key** (`LANGGRAPH_CLOUD_LICENSE_KEY`) - self-hosted instances
  report to LangChain's license server unless you buy an offline license. `langgraph dev` is free
  for *local development only*.

**Implication**: using the official packaged server/platform for production self-hosting is not
compatible with this plan's "fully open source" requirement, regardless of whether you pay for it
or not - the Agent Server component itself sits under a source-available, not open-source,
license once used in production. **Decision: do not use the packaged Agent Server or any
LangSmith Deployment tier in production.** Instead, build a small, custom backend service
(Apache-2.0/MIT-licensed tooling only - see §2.10) directly on top of the MIT-licensed `langgraph`
library, exposing only the HTTP/SSE surface the chosen frontend actually needs. This is more
build-it-yourself work than `langgraph up`, but it's the only way to keep the whole stack honestly
open source end to end.

> **Re-verify before implementation**: license terms and product names in this space change
> quickly (this plan's research reflects November 2026). Confirm the current Elastic
> License 2.0 terms and LangSmith Deployment's licensing model again at implementation time,
> ideally with a documented legal/licensing review, not just this plan's snapshot.

---

## 1. Target architecture (every layer, with its actual license)

| Layer | Component | License | Role |
|---|---|---|---|
| Frontend | **Agent Chat UI** (then **CopilotKit** core) | MIT | Chat interface; CopilotKit adds generative UI once ready (see `routing-lab3-chat-app-plan.md` §6) |
| Backend API | **Custom FastAPI service** (new, built here) | Apache-2.0 (FastAPI itself) | Thin HTTP/SSE layer over the compiled `app/chat` graph - replaces the Elastic-licensed Agent Server per §0 |
| Agent framework | **LangGraph** (library only) | MIT | The compiled graph itself (`build_graph()`, `build_chat_graph()`) |
| Conversation persistence | **PostgreSQL** + `langgraph-checkpoint-postgres` | MIT (checkpointer) / PostgreSQL License (Postgres itself, permissive) | Durable checkpointer backend, replacing `InMemorySaver` |
| Vector store | **Chroma** (already in use) | Apache-2.0 | Unchanged from `routing_lab2`/`routing_lab3` |
| LLM gateway / cost control | **LiteLLM** (OSS gateway) | MIT | Virtual keys, per-user/team budgets, rate limits, spend tracking, multi-provider routing |
| Cache / session / rate-limit store | **Valkey** (Linux Foundation Redis fork) | BSD-3-Clause | Avoids Redis Inc.'s post-2024 license ambiguity entirely - see §4 |
| AuthN/AuthZ | **Keycloak** | Apache-2.0 | SSO/SAML/OIDC/OAuth2, RBAC, multi-tenant realms |
| Secrets management | **OpenBao** (Linux Foundation Vault fork) | MPL-2.0 | Avoids HashiCorp Vault's 2023 BSL relicensing - see §4 |
| Guardrails / content safety | **LLM Guard** or **Guardrails AI** | MIT / Apache-2.0 | Prompt-injection detection, output scanning, PII detection (defense in depth alongside the project's own `sql_query.py` guard and citation-grounding design) |
| LLM/agent tracing | **MLflow** (already in use) | Apache-2.0 | Moves from "on-demand" (this repo's current dev-time pattern) to always-on, properly hosted |
| Infra metrics/logs/alerting | **Prometheus** + **Grafana** + **Loki** | Apache-2.0 / AGPLv3 / AGPLv3 | Reuses the exact pattern already demonstrated in `reference/rag_krish/agent_core/observability.py` (see `rag-krish-learnings.md` §7) |
| Tracing (OTel) | **OpenTelemetry** | Apache-2.0 | Standard instrumentation underneath MLflow/Prometheus |
| Containerization | **Docker** + **Kubernetes** + **Helm** | Apache-2.0 (Docker Engine/K8s/Helm) | Deployment/orchestration/packaging |
| Load testing | **Locust** | MIT | Pre-launch and ongoing capacity validation |
| CI/CD | **GitHub Actions** (pragmatic default, repo is already on GitHub) | - | See §4 for fully self-hostable alternatives if GitHub itself is a concern |

Every component above is either MIT, Apache-2.0, BSD-3, or MPL-2.0 - all OSI-approved, all usable
in a commercial product without per-seat/per-node licensing fees. None requires a vendor contract
to run in production.

---

## 2. Component-by-component plan

### 2.1 Authentication & authorization - **Keycloak**

Gap (from `routing-lab3-chat-app-plan.md` §8): "nothing exists today - the Streamlit dashboard and
`smarthome-csr` are both single-user dev tools."

- **Keycloak** (Apache-2.0, CNCF-adjacent, the most mature open-source IdP) provides SSO,
  SAML/OIDC/OAuth2, and realm-based multi-tenancy out of the box - genuinely enterprise-grade, used
  by large organizations as their production IdP, not a toy.
- The custom FastAPI backend (§2.10) validates Keycloak-issued JWTs on every request; the frontend
  (Agent Chat UI/CopilotKit) redirects through Keycloak's standard OIDC login flow.
- Multi-tenant isolation: map each Keycloak realm (or a custom tenant claim) to a `thread_id`
  namespace prefix, so one tenant's conversation history/checkpoints can never be queried by
  another's token.
- **Alternative considered**: Authentik (MIT, lighter-weight, good single-org fit) - recommend
  Keycloak specifically if genuine multi-tenant/enterprise SSO is a near-term requirement;
  Authentik is a reasonable lighter substitute otherwise.

**Done (basic single-realm authentication, not yet multi-tenant)**: Keycloak runs via
`routing_lab3/docker-compose.yml` (dev mode - see `infra/keycloak/README.md` for exactly what
still needs hardening for real production use), its realm/client/demo-users declared in
`infra/keycloak/realm-export.json`. `app/api/auth.py` verifies tokens against the realm's JWKS
endpoint; `ThreadOwnershipRegistry` enforces per-user thread isolation (not yet per-tenant realm
mapping - that's the one piece of this section's original scope not yet built, since this project
currently has one realm, not one per tenant). Verified end-to-end via a real browser login, and
via 8 new backend tests (`tests/test_chat_api.py`) covering missing/invalid/wrong-client tokens and
cross-user thread access. Frontend integration (`keycloak-js`, protected routes, bearer-token
requests) is recorded in `instructions/learnings/chat-ui-plan1.md` §4's Phase D, together with one
real limitation found: the frontend's Keycloak URL is baked in at Vite build time, unlike the
backend API's runtime-configurable nginx proxy (Phase C) - not yet fixed.

### 2.2 Durable persistence - **PostgreSQL + `langgraph-checkpoint-postgres`**

Gap: `routing-lab3-chat-app-plan.md` §6 explicitly scoped the checkpointer as `InMemorySaver`
first ("conversation history lost on every restart").

- Swap `InMemorySaver` for `langgraph.checkpoint.postgres.PostgresSaver` (MIT) once `app/chat/`
  exists - same `checkpointer=` parameter `smarthome-csr/app.py` already demonstrates, just a
  different backend class.
- Standard production Postgres operational practices apply: automated backups, point-in-time
  recovery, connection pooling (PgBouncer, MIT), and a documented restore drill *tested*, not just
  configured.
- This is additive to the existing `app/cache.py` SQLite LLM-response cache (which stays as a
  dev-cost-control tool, unrelated to conversation persistence) and `app/rag/manifest.py`'s
  incremental-indexing manifest (unrelated, stays file-based).

### 2.3 Rate limiting & cost controls - **LiteLLM**

Gap: "nothing stops a user from running up API costs; the project's `CachedEmbeddings`/SQLite LLM
cache helps during development, not against a malicious/runaway user in production."

- **LiteLLM** (MIT core - note the `enterprise/` subdirectory in its own repo is a separate paid
  license; the gateway/proxy and Python SDK used here are not) sits between every LLM call in this
  project (`ChatOpenAI`/`OpenAIEmbeddings` instantiations across `app/routers/`, `app/agents/`,
  `app/rag/embeddings.py`) and the actual provider.
- Gives per-user/per-team **virtual API keys** with independent budgets and rate limits, and
  **spend tracking** broken down by key/team/tag - exactly the missing piece for multi-tenant cost
  control.
- Routes to 100+ providers through one OpenAI-compatible endpoint, so this project's existing
  `ChatOpenAI(model=...)` calls need only an endpoint/key change, not a rewrite, to go through the
  gateway.
- Also provides fallback/load-balancing across providers - a genuine production reliability win
  beyond just cost control.

### 2.4 Security hardening

Gap: "that guard [sql_query.py's SELECT-only check] covers one tool; a production chat app facing
real users needs a broader look at prompt-injection resistance, output moderation, and abuse
handling generally."

- **Guardrails framework**: adopt **LLM Guard** (MIT) or **Guardrails AI** (Apache-2.0) as an
  input/output scanning layer in the new `app/chat/` entry point - prompt-injection detection on
  incoming messages, PII/secret leakage detection on outgoing answers, before either reaches the
  existing (unmodified) `build_graph()` pipeline or the user.
- **PII redaction precedent already exists in this repo's reference material**: port the pattern
  from `reference/rag_krish/agent_core/memory.py`'s `remember()` (redacts PII before persisting -
  see `rag-krish-learnings.md` §4 "memory.py") to anywhere conversation history gets durably
  stored (§2.2's Postgres checkpointer).
- **Secrets management**: move every API key/credential (OpenAI key, LiteLLM admin key, Keycloak
  client secrets, Postgres credentials) out of `.env` files into **OpenBao** (MPL-2.0, the Linux
  Foundation's fully open-source fork of HashiCorp Vault - see §4 for why Vault itself is excluded)
  - dynamic secrets, audit logging of every secret access, and automatic rotation.
- **Extend `sql_query.py`'s guard pattern project-wide**: that SELECT-only check (added earlier
  this session) is a good template for "validate before executing anything LLM-generated" - apply
  the same discipline to any future tool that executes generated code/queries, not just this one.

### 2.5 Observability & alerting

Gap: "this project's MLflow tracing is explicitly 'on-demand, not always-on' ... a real deployment
needs always-on logging, error alerting, and latency/cost dashboards."

- **Keep MLflow** (Apache-2.0, already used throughout this repo) for LLM-call tracing, but move it
  from the current "start it manually before testing" pattern (`start_mlflow.ps1`/`stop_mlflow.ps1`,
  matching the user's own stated preference for on-demand *dev* usage) to a properly hosted,
  always-on instance for production - a dedicated, backed-up Postgres-backed MLflow server, not the
  local SQLite `mlflow.db` this repo uses today.
- **Add infra-level metrics/logs/alerting that MLflow doesn't cover**: this exact gap was already
  solved once in this repo's reference material -
  `reference/rag_krish/agent_core/observability.py`'s `MetricsLoggingHandler` (Prometheus counters
  via a LangChain callback handler - see `rag-krish-learnings.md` §7) is a directly reusable
  pattern, not a new idea. Add **Grafana** (AGPLv3) for dashboards and **Loki** (AGPLv3) for log
  aggregation alongside Prometheus.
- **OpenTelemetry** (Apache-2.0) underneath both, for standard distributed tracing across the
  FastAPI backend → LangGraph → LiteLLM → provider call chain.
- Alerting rules (Prometheus Alertmanager, Apache-2.0) on the things that actually matter in
  production: elevated error rates, LLM latency/cost spikes, checkpointer write failures.

### 2.6 Scaling & deployment infrastructure

Gap: "horizontal scaling, load testing, a real CI/CD pipeline ... none of this exists yet for any
project in this repo."

- **Docker** images for the FastAPI backend, built from this project's existing `requirements.txt`
  conventions.
- **Kubernetes** (Apache-2.0) + **Helm** (Apache-2.0) for orchestration/packaging - horizontal
  scaling of the FastAPI backend is straightforward since LangGraph's actual conversation state
  lives in Postgres (§2.2), not in-process, so backend replicas are stateless and safely
  load-balanced.
- **Valkey** (BSD-3-Clause) for any cross-replica caching/session/rate-limit state the FastAPI
  layer itself needs (distinct from LiteLLM's own budget tracking, which LiteLLM persists itself).

### 2.7 CI/CD

- **GitHub Actions** as the pragmatic default, since this repo already lives on GitHub - not itself
  an open-source *product* you self-host, but zero additional infrastructure to stand up, and
  widely considered acceptable even in "open source stack" discussions since the pipeline
  definitions (`*.yml`) are themselves plain text/open and portable.
- **If avoiding any non-self-hostable dependency is a hard requirement**: **GitLab CE** (open
  source, self-hosted, MIT-ish terms for the Community Edition) or **Woodpecker CI** (Apache-2.0,
  a lightweight FOSS alternative to Drone) are fully self-hostable substitutes - flagging as an
  option, not defaulting to it, since it's a bigger operational lift for likely little practical
  gain over GitHub Actions for a repo that's already hosted there.

### 2.8 Load testing - **Locust**

- MIT-licensed, Python-based (fits this project's existing stack), scriptable load scenarios
  against the FastAPI backend - validate latency/throughput under concurrent multi-turn
  conversations specifically (not just single-request load), since the condensing step (§3 of
  `routing-lab3-chat-app-plan.md`) adds a sequential LLM call per turn that single-request
  benchmarks would miss.

### 2.9 Data retention & privacy policy

This is a policy decision, not a tool choice - but needs to be made explicitly, not left implicit:

- Define a **retention window** for conversation history stored in Postgres (§2.2) - e.g., N days
  of raw history before automatic deletion/anonymization, consistent with whatever data-handling
  commitments the eventual product makes to its users.
- **Right-to-delete**: a concrete mechanism (an admin endpoint or scheduled job) to purge a given
  user's/tenant's conversation history and checkpoints on request, not just a stated policy with
  no implementation.
- PII redaction (§2.4) reduces exposure but is not a substitute for an explicit retention policy -
  both are needed.

### 2.10 Frontend + backend bridge - the custom FastAPI service

Per §0, this project builds its own thin API layer rather than running the Elastic-licensed
packaged Agent Server:

- A FastAPI (Apache-2.0-style permissive) service wraps `app/chat/graph.py`'s compiled graph
  directly via the MIT-licensed `langgraph` library's own `.astream()`/`.ainvoke()` methods - no
  `langgraph-api` dependency.
- Exposes whatever streaming contract **Agent Chat UI** actually needs to render incrementally
  (SSE or WebSocket) - this needs a concrete compatibility check against Agent Chat UI's expected
  API shape before relying on it (Agent Chat UI's documented environment variables
  `LANGGRAPH_API_URL`/`NEXT_PUBLIC_API_URL` suggest it's built to talk to *a* LangGraph-server-like
  API, not necessarily requiring the official packaged implementation specifically - **this
  compatibility needs to be verified hands-on early in implementation**, since it's the one part
  of this plan resting on an assumption rather than a confirmed fact).
- Same FastAPI service later mounts the **AG-UI bridge** for CopilotKit once that phase starts
  (§6 of `routing-lab3-chat-app-plan.md`) - CopilotKit's documented integration pattern already
  expects "an HTTP app that mounts the AG-UI FastAPI bridge next to the graph API," which maps
  cleanly onto a self-built FastAPI service either way.
- Validates Keycloak JWTs (§2.1) on every request; every LLM call made from inside the graph goes
  through LiteLLM (§2.3), not directly to a provider.

---

## 3. Phased rollout (sequenced, with dependencies)

1. **Phase A - Security & auth foundation.** Keycloak (§2.1) + OpenBao (§2.4) + guardrails
   framework (§2.4). Done first because retrofitting auth/secrets handling onto an already-running
   system is much harder than building on it from day one.
2. **Phase B - Backend service + durable persistence.** The custom FastAPI service (§2.10) +
   PostgreSQL checkpointer (§2.2), built directly on top of `routing_lab3/app/chat/` once Phase 0
   of `routing-lab3-chat-app-plan.md` is validated. **Exit criteria**: the existing 228-row/10-level
   ground-truth suite still passes unchanged (the underlying `build_graph()` pipeline is untouched
   by any of this), plus new multi-turn conversations survive a backend restart.
3. **Phase C - Cost/rate limiting.** LiteLLM (§2.3) placed in front of every provider call.
   **Exit criteria**: a deliberately budget-exceeding test user is correctly rate-limited/blocked
   without affecting other users' quotas.
4. **Phase D - Observability.** MLflow moved to always-on hosted mode + Prometheus/Grafana/Loki/OTel
   (§2.5). **Exit criteria**: a deliberately induced failure (e.g., a bad API key) triggers a real
   alert, not just a log line nobody's watching.
5. **Phase E - Frontend integration.** Agent Chat UI first (validate the FastAPI bridge's
   compatibility per §2.10's flagged assumption), CopilotKit once generative UI is wanted.
6. **Phase F - Scaling & deployment infra.** Docker/Kubernetes/Helm (§2.6) + CI/CD (§2.7).
   **Exit criteria**: a rolling deployment with zero downtime, verified by load-testing through a
   deploy (§2.8's Locust scenarios, run as part of Phase G).
7. **Phase G - Load testing + data retention/compliance finalization.** Locust (§2.8) load
   scenarios specifically covering multi-turn conversation latency, plus the retention/right-to-
   delete mechanism (§2.9) actually implemented and tested, not just documented.

Every phase keeps the same non-negotiable bar this whole project has used throughout: **the
existing single-question routing pipeline's 228-row ground truth must not regress**, since nothing
in this plan touches `app/graph.py`'s `build_graph()` itself.

---

## 4. What this plan explicitly avoids, and why

| Avoided | Reason | Chosen alternative |
|---|---|---|
| **LangSmith Deployment / packaged Agent Server (`langgraph-api`)** in production | Elastic License 2.0 + requires a paid Enterprise license key for production self-hosting (§0) - not actually open source once in production | Custom FastAPI service directly on the MIT-licensed `langgraph` library (§2.10) |
| **Redis** (core, post-2024) | Redis Inc. moved core Redis to SSPL/RSALv2-style licensing in 2024, creating real ambiguity about commercial self-hosting terms, even though some of this has since shifted again - safer to sidestep the question entirely | **Valkey** (BSD-3-Clause, Linux Foundation-governed fork with no such ambiguity) |
| **HashiCorp Vault** (post-2023) | Relicensed to the Business Source License (BSL) in 2023 - not OSI-approved open source | **OpenBao** (MPL-2.0, the Linux Foundation's fork of pre-BSL Vault) |
| **Chainlit** | A reasonable chat-UI option in principle, but its upstream repository was archived in October 2026 (confirmed via web search this session) - not a safe long-term dependency to build on now | Agent Chat UI / CopilotKit (both actively maintained, MIT) |

---

## 5. Acceptance checklist for "production-ready" and "enterprise-ready" claims

- [ ] Auth: a real SSO login flow works end-to-end through Keycloak; a token from tenant A cannot
      read tenant B's conversation history.
- [ ] Persistence: killing and restarting the FastAPI backend/Postgres container pair preserves an
      in-progress conversation exactly where it left off.
- [ ] Cost control: a LiteLLM-enforced budget cap actually blocks further requests once exceeded,
      verified with a deliberate test, not just configured and assumed to work.
- [ ] Security: a deliberate prompt-injection attempt and a deliberate non-SELECT SQL attempt
      (extending the existing `sql_query.py` test pattern from this session) are both caught before
      reaching either the LLM or the database.
- [ ] Observability: a deliberately induced failure produces a real alert within a defined SLA
      (e.g., under 5 minutes), not just a log entry.
- [ ] Scaling: a rolling Kubernetes deployment completes with zero dropped requests, verified under
      simultaneous Locust load.
- [ ] Data governance: the right-to-delete mechanism actually removes a given user's data from
      Postgres and any Loki-retained logs, verified by checking afterward, not just by reading the
      code that's supposed to do it.
- [ ] **Regression**: the existing 228-row/10-level routing-accuracy ground truth suite
      (`routing_lab3/tests/`) still passes unchanged, end to end, after every phase above.
- [ ] **License audit**: every dependency actually added during implementation (not just the ones
      planned here) is re-checked against its real license before shipping - dependency licenses
      can change between when this plan was written and when it's implemented.

---

## 7. Cloud deployment mapping (Azure now, portable to AWS later)

**Decisions** (resolving the three open questions this section originally left unanswered):
Azure for now, built so switching to AWS later is a hosting-target change, not a re-architecture;
less operational overhead; maximally open-source/portable for secrets and observability. Those
three decisions are mostly complementary, with one real tension worth resolving explicitly rather
than glossing over - see the Container compute row below.

| Concern | Azure (now) | AWS (future-portable) | Notes |
|---|---|---|---|
| Container compute | **AKS** (managed Kubernetes) | **EKS** (managed Kubernetes) | **Resolving the tension between "less ops overhead" and "easily switched to AWS":** Azure Container Apps looks like the lower-ops option at first glance, but it's an Azure-proprietary orchestration model with no direct AWS equivalent - moving to AWS would mean re-architecting the deployment, not just repointing it. Managed Kubernetes (AKS now, EKS later) actually satisfies *both* requirements at once: Azure/AWS manage the control plane, patching, and HA (the genuinely heavy ops burden), while the Helm charts, Docker images, and `kubectl`/Kubernetes API surface from §2.6 are **identical on both clouds** - switching providers later is a `kubeconfig` and Helm `values.yaml` change, not a rewrite. This is the recommended choice specifically *because* "less ops overhead" and "AWS-portable" point the same direction here, not opposite ones. |
| Container registry | **Azure Container Registry (ACR)** | **Amazon ECR** | Both are plain OCI registries - the same Docker images from §2.6 push to either with a registry-URL change only |
| Conversation persistence (§2.2) | **Azure Database for PostgreSQL - Flexible Server** | **Amazon RDS for PostgreSQL** (or Aurora PostgreSQL) | Recommended over self-hosting Postgres on a VM either way - same open-source Postgres engine; `langgraph-checkpoint-postgres` (MIT) just needs a connection string, indifferent to who manages the server. Migration path: standard `pg_dump`/`pg_restore`, no application changes |
| Secrets management (§2.4) | **OpenBao, self-hosted** (decided - not Azure Key Vault) | **OpenBao, self-hosted** (same deployment, unchanged) | Resolved per "maximally open-source/portable": OpenBao runs as just another container on AKS/EKS either way, so this row genuinely doesn't change when switching clouds - the whole reason it was worth deciding explicitly |
| Identity/SSO (§2.1) | **Keycloak, self-hosted** (already the §2.1 default) | **Keycloak, self-hosted** (same deployment, unchanged) | Already aligned with the portability decision - no change needed. Optionally federates upstream to Entra ID (Azure) or IAM Identity Center (AWS) later if the org's existing directory needs to be the source of truth, without changing anything else |
| LLM gateway (§2.3) | **LiteLLM, self-hosted** | **LiteLLM, self-hosted** (same deployment, unchanged) | Cloud-agnostic by construction - sits in front of OpenAI specifically, runs identically either way |
| Observability (§2.5) | **Prometheus/Grafana/Loki, self-hosted** (decided - not Azure Monitor/Application Insights) | **Prometheus/Grafana/Loki, self-hosted** (same deployment, unchanged) | Resolved the same way as secrets: genuinely portable, no cloud-specific rework when switching. MLflow stays self-hosted either way regardless |
| Cache/session store (§2.6) | **Valkey, self-hosted** (container, consistent with the portability decision) | **Valkey, self-hosted**, or **Amazon ElastiCache for Valkey** if a managed option is wanted later | AWS added native managed Valkey support specifically in response to the Redis licensing change - worth knowing it exists, but self-hosted Valkey is the more portable default for now, consistent with the other rows above |
| Ingress/load balancing | **NGINX Ingress Controller** or **Traefik** (both open source, deployed as a Kubernetes `Ingress`/`IngressRoute` via Helm) | **Same NGINX Ingress Controller/Traefik**, unchanged | Extending the same portability logic to networking, even though it wasn't explicitly asked about: a cloud-native Azure Application Gateway/AWS ALB integration would need to be rebuilt when switching clouds, whereas a Kubernetes-native ingress controller is just another Helm chart - identical on AKS and EKS. (Azure/AWS's own load balancer still sits underneath, fronting the ingress controller's `LoadBalancer`-type service - that thin layer is unavoidable either way, but the routing/TLS/cert-manager configuration above it stays 100% portable.) |
| LLM provider | **OpenAI API** (unchanged, paid, already in use throughout this project) | **OpenAI API** (unchanged, paid, already in use throughout this project) | No change from this project's current architecture - LiteLLM sits in front of it for budget/rate-limit enforcement only |

**Net effect of these decisions**: with this row-by-row mapping, essentially everything *except*
the managed Postgres service and the container registry is now a plain Kubernetes workload
(Keycloak, OpenBao, LiteLLM, Prometheus/Grafana/Loki, the NGINX/Traefik ingress controller, the
FastAPI backend itself) - deployed via the same Helm charts regardless of which cloud's managed
Kubernetes is underneath. Migrating from Azure to AWS later should be close to: point `kubectl` at
an EKS cluster, re-run the same Helm releases, repoint the Postgres connection string at RDS, and
restore a `pg_dump` - not a rewrite of the application or its surrounding services.

---


## 8. Relationship to other documents

- Builds directly on [routing-lab3-chat-app-plan.md](./routing-lab3-chat-app-plan.md) (the
  conversational-AI prototype this plan hardens) - that plan's Phase 0-2 should be validated first;
  this plan's Phase A onward can start in parallel once Phase 0 proves the condensing/wrap-the-
  existing-pipeline design works.
- Reuses two patterns already demonstrated in this repo's reference material rather than inventing
  them: Prometheus-via-callback-handler and PII redaction, both from
  [rag-krish-learnings.md](./rag-krish-learnings.md) §4/§7.
- [chat-ui-plan1.md](./chat-ui-plan1.md) is the frontend-specific companion to this plan - it plans
  `routing_lab3/frontend/`'s own path to production readiness (UX completeness, accessibility,
  testing, containerization, auth integration) without redeciding any component chosen here, and
  surfaces one backend gap back into this plan's §2.1 rollout (a `thread_id` ownership check
  needed once Keycloak auth lands - see that document's §6).
- Follows the same evidence-based, zero-regression discipline established throughout
  [routing-project-learnings.md](./routing-project-learnings.md) and
  [routing-lab2-learnings.md](./routing-lab2-learnings.md) - every phase above has an explicit exit
  criterion, not just a task list.
