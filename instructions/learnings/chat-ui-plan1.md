# `routing_lab3/frontend` production-readiness plan

## 0. Scope and relationship to other plans

This document plans the UI-specific work needed to take `routing_lab3/frontend/` (the custom
Vite + React + TypeScript + Tailwind chat UI built this session) from a validated prototype to
production-ready - it is the **frontend companion** to two existing documents, not a replacement
for either:

- [`routing-lab-prod-plan.md`](./routing-lab-prod-plan.md) - the overall app production plan
  (auth provider, durable persistence, rate limiting, security hardening, observability, scaling,
  CI/CD, cloud mapping). That plan's component choices (Keycloak, PostgreSQL, LiteLLM, OpenBao,
  Prometheus/Grafana/Loki, AKS/EKS) are **not re-decided here** - this document only covers how the
  frontend integrates with them once built.
- [`routing-lab3-chat-app-plan.md`](./routing-lab3-chat-app-plan.md) - designed the conversational
  layer itself (condensing, wrap-the-existing-pipeline architecture) and already recorded why
  Agent Chat UI was explored and not adopted, in favor of the custom frontend this plan now hardens.

**What "production ready" means for the UI specifically, scoped by this document**: a real user
can securely log in, have a reliable multi-turn conversation with correctly rendered answers and
citations, recover gracefully from errors, use it on a phone, and the whole thing is tested,
containerized, and deployed the same portable way as the rest of this project - not just "it works
when I click through it manually," which is as far as this session's validation went.

---

## 1. Current state (what's actually built and validated)

`routing_lab3/frontend/` is a single-page app: `src/api/client.ts` (typed fetch client for
`app/api/main.py`'s `/chat`/`/chat/stream`, including manual SSE parsing), `src/hooks/useChat.ts`
(conversation state, `thread_id` persisted in `localStorage`), and three components
(`ChatWindow`/`Composer`/`RoutingDetails`). Verified end-to-end via real browser testing this
session: single-turn Q&A, SSE streaming status updates, multi-turn follow-up resolution, and
`RoutingDetails` correctly rendering real topic/chapter breadcrumbs, cited passages with scores,
and a tool-call card (an actual `sql_query` SELECT and its result).

**Explicitly not yet there** (the gap this plan addresses): no automated tests of any kind, no
authentication, one conversation per browser forever (no list/switcher, no "new conversation"),
plain-text rendering only (no Markdown), no accessibility pass, no Docker packaging or CI, no
frontend error reporting, and no verification beyond a desktop browser at `localhost`.

---

## 2. Gap analysis & planned enhancements

### 2.1 Conversational UX completeness

- **Markdown rendering.** Answers can contain lists/emphasis/code (the synthesis agent's prose
  already reads like structured text); today it's rendered as literal `whitespace-pre-wrap` text.
  Add **`react-markdown`** (MIT) with **`rehype-sanitize`** (MIT) - the sanitize step is defense in
  depth against any HTML a prompt-injected or misbehaving LLM response might contain, even though
  this project's answers come from a controlled pipeline, not raw user-supplied HTML.
- **Multiple conversations.** Today's single `localStorage` `thread_id` means a user can never
  start a new, separate conversation or revisit an old one. Needs a "New conversation" action
  client-side, plus (see §2.3) a backend endpoint to list a user's threads once conversations are
  tied to an authenticated identity rather than an anonymous browser-local ID.
- **Copy-to-clipboard** on each assistant answer.
- **Auto-scroll to the latest message** while streaming, with a "jump to latest" affordance if the
  user has scrolled up to re-read earlier context (don't fight someone who's scrolled away on
  purpose).
- **Retry/regenerate** on a turn that errored or returned "insufficient information."
- **Polish existing loading/error states**: disable the composer while an error banner is showing
  stale information, distinguish a network failure from a backend-returned error, auto-clear an
  old error once a new send succeeds.
- **Mobile responsiveness**: the current `max-w-2xl mx-auto` layout is untested below desktop
  width - verify and fix at common breakpoints (not just assume Tailwind defaults are enough).
- **Dark mode** (low priority, cheap via Tailwind's `dark:` variants given the stack already in
  place).

### 2.2 Accessibility (a11y)

- **ARIA live region** around the assistant message area so screen readers announce streaming
  status updates and the final answer as they arrive, not just silently update the DOM.
- **Semantic roles/labels**: `role="log"` on the chat history, an explicit `<label>`/`aria-label`
  on the composer's input (currently relies on placeholder text alone, which isn't a substitute for
  a label).
- **Keyboard-only operability**: Enter-to-send already works via native form submission; verify
  focus returns to the input after sending, and that the "Routing details" `<details>` toggle and
  any future retry/copy buttons are fully keyboard-reachable.
- **Color contrast**: check the slate/amber/green `RoutingDetails` badges against WCAG AA, not just
  "looks fine on my monitor."
- **Automated enforcement**: **`axe-core`** (MPL-2.0, Deque's accessibility engine) wired into the
  test suite (§2.4) so a11y regressions fail CI instead of relying on manual spot-checks.

### 2.3 Security (frontend-specific - backend security hardening is `routing-lab-prod-plan.md` §2.4)

- **Sanitize all rendered Markdown/HTML** (§2.1's `rehype-sanitize`) before it ever reaches the DOM.
- **Auth integration**: once Keycloak (`routing-lab-prod-plan.md` §2.1) is live, the frontend needs
  a real OIDC flow. Recommend **`keycloak-js`** (Apache-2.0, Keycloak's own official JS adapter) or
  **`oidc-client-ts`** (Apache-2.0, provider-agnostic) - a protected-route wrapper, the access token
  attached as `Authorization: Bearer` on every `/chat` request, automatic silent token refresh, and
  logout clearing all local conversation state.
- **A real authorization gap this plan surfaces, not just a frontend nice-to-have**: today, any
  client can set an arbitrary `thread_id` and the backend (`app/api/main.py`) will happily resume
  *that* conversation - nothing currently checks that the caller actually owns it. This is a
  backend fix (verify the authenticated user owns `thread_id` before resuming it, once Keycloak
  auth exists), but it's called out here because the frontend's current client-generated,
  unauthenticated `localStorage` `thread_id` pattern is exactly what makes the gap easy to miss -
  see §6 below for the explicit cross-link into `routing-lab-prod-plan.md`.
- **Content-Security-Policy** header (set by whatever serves the production static build - the
  nginx config in §2.5) restricting `script-src` to `'self'`, no inline scripts.
- **No secrets in frontend code or env vars.** Vite's `VITE_*` variables are compiled into the
  public bundle, not kept server-side - only ever put the API base URL there, never a credential.
  (In production, per §2.5, a reverse proxy removes the need for this variable entirely.)

### 2.4 Testing (currently: zero automated tests of any kind)

- **`vitest`** (MIT, Vite-native, near-zero extra config given the existing `vite.config.ts`) +
  **`@testing-library/react`** (MIT) for component/hook unit tests: `useChat`'s state transitions
  (streaming vs. non-streaming, error handling, abort-on-unmount), `RoutingDetails` rendering for
  each summary shape (empty/no-topics, with a tool result, with a multi-hop trace, with recovered
  vs. unrecovered recovery attempts), `ChatWindow`'s empty-state and message-list rendering.
- **`@playwright/test`** (Apache-2.0, Microsoft) for an automated end-to-end smoke test - this
  codifies the manual browser validation already performed this session (send a message, observe
  streaming status, observe the final answer, expand "Routing details" and see citations/tool
  results) into a repeatable, CI-runnable test instead of a one-off manual check.
- **`axe-core`** (§2.2) integrated as part of the Playwright/component test run.
- **Lint/format in CI**: `oxlint` (MIT, already present in `package.json`) plus a formatting check
  (**Prettier**, MIT) - neither exists in CI today since there is no CI yet (§2.5).

### 2.5 Build & deployment

- **Dockerize**: a multi-stage build - a Node builder stage running `npm run build`, then a minimal
  static-file stage (`nginx:alpine` or an equivalently tiny static server) serving `dist/`.
- **Reverse-proxy `/api` in production, not just in Vite's dev server.** Today, `vite.config.ts`'s
  `server.proxy` only helps `npm run dev`; production needs the same effect from whatever serves
  the static build - the production nginx container (or the cluster's own ingress) proxies
  `/api/*` to the FastAPI backend service. This keeps the frontend **same-origin** with the API in
  both environments, so `VITE_API_BASE_URL` never needs to be set at all in production - consistent
  with `routing-lab-prod-plan.md` §7's NGINX/Traefik ingress decision, and avoiding the classic
  "Vite env vars are baked in at build time, not reconfigurable at container runtime" trap entirely,
  rather than working around it.
- **CI**: GitHub Actions (consistent with `routing-lab-prod-plan.md` §2.7's default) running
  build + lint + unit tests + the Playwright smoke test on every PR touching `frontend/`.
- **Bundle size budget**: a simple check (e.g. **`size-limit`**, MIT) so a future dependency (a
  large syntax-highlighter, say) can't silently bloat the bundle unnoticed.

### 2.6 Performance

- Current bundle is small (~227 KB JS / ~71 KB gzipped) for a minimal app - fine today, but
  revisit once Markdown rendering (§2.1) is added, since that category of library can add real
  weight; prefer the lightest option that does the job (e.g. skip a full code syntax-highlighter
  unless answers actually contain code blocks often enough to justify it).
  **Measured after §2.1 landed**: `react-markdown` + `rehype-sanitize` (plus their `unified`
  ecosystem dependencies) grew the bundle to ~353 KB JS / ~109 KB gzipped - a real, predicted
  increase, not a regression to investigate. Still small in absolute terms; the bundle-size budget
  in §2.5/§3 (`size-limit`) should be set with this as the new informed baseline, not the earlier
  227 KB figure.
- Code-split anything added later that isn't needed on first paint (e.g. a future conversation-list
  sidebar) via `React.lazy`.
- Verify streaming renders incrementally without layout thrashing under real (non-`localhost`)
  network latency, not just the instant local responses seen during this session's testing.

### 2.7 Observability (frontend-specific - backend observability is `routing-lab-prod-plan.md` §2.5)

- Wrap the app in a **React error boundary**; report caught errors to the same self-hosted
  Grafana/Loki stack `routing-lab-prod-plan.md` §2.5 already plans for the backend (a small
  `/client-error` logging endpoint on the FastAPI service, forwarding into Loki), rather than
  adopting a separate proprietary SaaS (e.g. Sentry) - consistent with this project's stated
  preference for self-hosted, portable observability.
- Optional, privacy-respecting basic usage signals (turns per session, client-side error rate) -
  opt-in, no third-party analytics SDK, nothing that conflicts with `routing-lab-prod-plan.md`
  §2.9's data-retention/privacy posture.

---

## 3. Proposed additions (name, purpose, license)

| Addition | Purpose | License |
|---|---|---|
| `react-markdown` | Render answer Markdown safely | MIT |
| `rehype-sanitize` | Strip unsafe HTML from rendered Markdown | MIT |
| `keycloak-js` or `oidc-client-ts` | OIDC login flow against Keycloak (`routing-lab-prod-plan.md` §2.1) | Apache-2.0 |
| `vitest` | Component/hook unit tests | MIT |
| `@testing-library/react` | Component testing utilities | MIT |
| `@playwright/test` | End-to-end smoke tests | Apache-2.0 |
| `axe-core` | Automated accessibility checks | MPL-2.0 |
| Prettier | Code formatting check in CI | MIT |
| `size-limit` | Bundle size budget enforcement | MIT |

Every addition here is open source and self-hostable/buildable with no paid tier required -
consistent with the rest of this repo's stack.

---

## 4. Phased rollout

1. **Phase A - UX completeness essentials.** Markdown rendering + sanitization, copy button,
   auto-scroll, retry/regenerate, loading/error-state polish, mobile responsiveness pass. No
   backend dependency - can start immediately. **Exit criteria**: a manual pass through the same
   scenarios already validated this session (single-turn, multi-turn, tool call) now additionally
   renders Markdown correctly, survives a deliberately induced network failure gracefully, and
   looks correct at a phone-width viewport.
   **Done**: `react-markdown` + `rehype-sanitize` (`MarkdownMessage.tsx`), `CopyButton.tsx`,
   auto-scroll with a "Jump to latest" affordance in `ChatWindow.tsx` (follows an incoming answer
   only if the user hasn't scrolled up; always follows the user's own freshly-sent message),
   a `retryLastMessage` path in `useChat.ts` wired to a "Retry" button in the error banner, and a
   network-vs-backend-error distinction (`describeError`). Verified via real browser testing: a
   502 induced by stopping the backend mid-conversation showed the error+Retry banner, and
   clicking Retry after restarting the backend resent the same message and completed successfully;
   a 375px-wide viewport showed no overflow/truncation. `h-screen` was also switched to `h-dvh`
   (dynamic viewport height), a real mobile-Safari-address-bar fix, not just a cosmetic tweak.
2. **Phase B - Testing foundation.** `vitest`/`@testing-library/react` unit tests, the Playwright
   e2e smoke test, `axe-core` wired in, CI running all of it. Deliberately placed **before** further
   feature growth - nothing is tested today, and this project's own evidence-based culture (the
   228-row/10-level ground-truth discipline the rest of the repo lives by) argues for catching the
   frontend up early rather than accumulating more untested surface area first. **Exit criteria**:
   CI fails on a deliberately introduced regression in each of `useChat`, `RoutingDetails`, and the
   e2e flow.
   **Done**: 17 `vitest`/Testing Library unit/component tests (`useChat`, `RoutingDetails`,
   `ChatWindow`, `MarkdownMessage` - including a sanitization test confirming a `<img onerror=...>`
   payload never reaches the DOM, and `CopyButton`), 3 Playwright e2e tests
   (`e2e/chat.spec.ts`) mocking `/api/chat/stream` at the network boundary rather than requiring a
   live LLM-backed server - deliberate, since the pipeline's own correctness is already covered
   exhaustively by `routing_lab3/tests`' ground truth; this suite's job is the frontend's own
   behavior (SSE parsing/rendering/error-retry), which it now actually does cover end-to-end,
   including the exact send→stream→expand-citations flow and the error+Retry flow validated
   manually in Phase A. The third e2e test runs `@axe-core/playwright` against a populated
   conversation and found **zero serious/critical accessibility violations** on the first try - a
   genuine, not just assumed, positive result from the semantic HTML already in place. CI wired via
   `.github/workflows/routing-lab3-frontend-ci.yml` (build+lint+unit+e2e on every change under
   `routing_lab3/frontend/`).
3. **Phase C - Containerization & deployment.** Dockerfile, production nginx reverse-proxy config
   for `/api`, CI build/push. Depends on nothing else here, needed before any real deployment
   regardless of auth/backend progress. **Exit criteria**: the containerized frontend, pointed at a
   real (non-`localhost`) backend URL purely via the reverse proxy, round-trips a real conversation
   with no `VITE_API_BASE_URL` set.
4. **Phase D - Auth integration.** OIDC flow against Keycloak, protected routes, bearer-token
   requests. Depends on `routing-lab-prod-plan.md` Phase A (Keycloak live) **and** on the backend
   adding the thread-ownership check flagged in §2.3/§6 - both need to land together, since an OIDC
   login with no corresponding backend authorization check would be security theater. **Exit
   criteria**: logging in as user A and attempting to resume user B's `thread_id` is rejected.
5. **Phase E - Multi-conversation UX + observability.** Conversation list/switcher (needs the
   server-side thread-listing-per-user endpoint Phase D's auth makes possible), frontend error
   reporting into Grafana/Loki. Depends on Phase D (threads scoped per user) and
   `routing-lab-prod-plan.md` Phase D (observability stack live). **Exit criteria**: a user sees
   only their own past conversations, and a deliberately induced frontend error shows up in Grafana
   within the same SLA `routing-lab-prod-plan.md` §5 already defines for backend alerts.

---

## 5. Acceptance checklist

- [ ] A real user can complete a multi-turn conversation with correctly rendered Markdown and
      working citations/tool-result panels, on both desktop and a phone-width viewport.
- [ ] `vitest`/Testing Library unit tests and a Playwright e2e smoke test both run in CI and fail on
      a deliberately introduced regression.
- [ ] `axe-core` reports no violations on the chat screen.
- [ ] The production container serves the app and proxies `/api` correctly with zero
      frontend-side environment configuration.
- [ ] Logging in via Keycloak works end-to-end; a token from one user cannot resume another user's
      `thread_id` (the gap identified in §2.3/§6).
- [ ] A deliberately induced frontend error (e.g. throwing inside a component) is caught by the
      error boundary and appears in Grafana/Loki, not just the browser console.
- [ ] Bundle size stays within the budget set in §2.5; a regression here is visible in CI, not
      discovered after deployment.
- [ ] **Regression**: `routing_lab3/tests/`' existing 228-row/10-level routing-accuracy ground
      truth is completely unaffected, since nothing in this plan touches any Python backend logic
      beyond the thread-ownership check explicitly called out in §6.

---

## 6. A gap this plan surfaces for `routing-lab-prod-plan.md`

While scoping the UI's auth integration (§2.3/Phase D), this plan identified a **backend**
authorization gap not previously called out: `app/api/main.py` never verifies that the caller
making a `/chat` request actually owns the `thread_id` it supplies - today, any `thread_id` resumes
that conversation for anyone who guesses or is given it. This is harmless in the current
single-user, unauthenticated prototype, but must be fixed as part of
`routing-lab-prod-plan.md`'s §2.1 (Keycloak) rollout, not left implicit: once requests carry a
validated JWT, the backend should reject (or 404, to avoid confirming existence) any `/chat`/
`/chat/stream` call where the token's identity doesn't match the `thread_id`'s recorded owner.

---

## 7. Relationship to other documents

- Hardens the frontend built in [routing-lab3-chat-app-plan.md](./routing-lab3-chat-app-plan.md)'s
  Phase 1 (production path) - that document's phased rollout and this one's are sequenced
  independently; this plan's Phase A-C need nothing from either other document, Phase D-E do.
- Integrates with, but does not redecide, any backend/infrastructure component chosen in
  [routing-lab-prod-plan.md](./routing-lab-prod-plan.md) - Keycloak (§2.1), Prometheus/Grafana/Loki
  (§2.5), and the NGINX/Traefik ingress decision (§7) are all referenced here as fixed inputs.
  §6 above is this plan's one piece of feedback into that document (a backend gap surfaced by
  frontend auth planning, not a frontend-side fix).
- Follows the same evidence-based, phased-with-exit-criteria discipline used throughout this
  repo's planning documents (`routing-project-learnings.md`, `routing-lab2-learnings.md`,
  `routing-lab-prod-plan.md`) rather than a plain task list.
