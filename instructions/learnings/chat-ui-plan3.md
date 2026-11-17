# `routing_lab3/frontend` UI plan 3 - proposed next features

## 0. Scope and relationship to other plans

Third UI planning document for `routing_lab3/frontend`, following the same evidence-based,
phased-with-exit-criteria discipline as its predecessors:

- [`chat-ui-plan1.md`](./chat-ui-plan1.md) - took the prototype to production-ready (Phases A-E
  all done: tests, Docker, auth, multi-conversation UX, error boundary). Its still-open items
  (size-limit bundle budget, Prettier in CI, runtime-configurable Keycloak URL, Grafana/Loki
  deployment) remain tracked **there**, not re-planned here.
- [`chat-ui-plan2.md`](./chat-ui-plan2.md) - external redesign advice; its groups 1-3 are
  implemented (conversation-meta routing, ChatGPT-style polish, sidebar management), three items
  were explicitly rejected with reasons, and its big developer-tooling pages were deferred. This
  document picks those deferred items up and adds new proposals.

**What's different about this plan**: every proposal in §1 below traces to something *actually
observed* during this branch's live testing sessions - not speculative feature brainstorming.
The §2 items are the plan2 deferrals, unchanged in intent, now sequenced.

---

## 1. Proposals grounded in observed incidents

### 1.1 Undo-able delete (trash), instead of immediate hard delete

**Evidence**: during live testing, a stale sidebar search filter caused the wrong conversation to
be deleted - the two-step Confirm? worked exactly as designed, and the conversation was still
irrecoverably gone in one second. The same mistake is one mis-tap away for any real user.

- Backend: `DELETE /threads/{id}` becomes a soft delete (a `deleted_at` column on
  `thread_owners`; excluded from `GET /threads`); a new `POST /threads/{id}/restore` undoes it.
  Hard-delete (ownership row + `checkpointer.delete_thread`) runs on a sweep for rows
  soft-deleted more than N days ago, or immediately via an explicit `?permanent=true`.
- Frontend: after delete, a transient "Conversation deleted - Undo" toast (5-10 s). No separate
  trash UI needed initially - the toast covers the observed mistake class.
- **Exit criteria**: delete the active conversation, click Undo, and both the sidebar entry and
  the full message history are back; a soft-deleted thread's `thread_id` cannot be resumed via
  `/chat` while deleted.

### 1.2 LLM-generated conversation titles

**Evidence**: two conversations titled "What does washing machine error E21 mean?" were
indistinguishable in the sidebar (same opening message → same title) - which directly enabled
the §1.1 wrong-deletion incident. Raw first-message titles also truncate badly ("What does
washing ma…").

- After a conversation's first turn completes, generate a 3-6 word title (one small
  structured-output call, same pattern as `condense.py`) and store it via the existing title
  column; the user's manual rename (✎) always wins - never overwrite a user-set title (track
  with a `title_is_custom` flag).
- **Exit criteria**: two conversations opened with the same first message get distinct,
  descriptive titles; renaming one manually is never clobbered by a later turn.

### 1.3 Humanized progress labels

**Evidence**: during 30-60 s turns the status bubble shows raw graph node names -
"Working: invoke_routing_pipeline…", "Working: check_output…" - developer vocabulary in a user
surface.

- A small frontend map from node name → user phrasing ("Understanding your question…",
  "Searching the knowledge base…", "Checking the answer…"), falling back to the raw name for
  unknown nodes so new graph nodes degrade gracefully rather than break.
- **Exit criteria**: every node in `app/chat/graph.py` and the inner routing pipeline that can
  emit a status event has a human label; unknown names still render.

### 1.4 Starter prompts on the empty state

**Evidence**: the knowledge base spans six topics (appliances, Azure, customer support, data
engineering, finance, Python), but testers only ever asked appliance questions - nothing in the
UI reveals what the assistant actually knows.

- Replace the bare "Ask a question… to get started" line with 4-6 clickable example chips drawn
  from the ground-truth datasets (one per major topic, e.g. the E05, restocking-fee, APR/APY,
  and multi-hop refrigerator questions already validated live). Clicking a chip sends it.
- **Exit criteria**: a new conversation shows the chips; clicking one sends that exact question;
  chips disappear once the first message is sent.

### 1.5 Stop waiting on an in-flight turn

**Evidence**: multi-hop turns took 60 s+ during testing with no way to bail out; the composer is
locked the whole time. (Distinct from plan2's rejected token streaming - this cancels the
*client's wait*, via the `AbortController` already wired into `useChat`, not the server's
guardrail ordering.)

- A "Stop" button beside the status bubble aborts the fetch, re-enables the composer, and marks
  the turn "Stopped - the answer may still be recorded server-side" (the graph does finish and
  `record_turn` persists it; a later history restore will show the completed answer - document
  this semantic honestly rather than pretending the server stopped).
- **Exit criteria**: clicking Stop during a streaming turn frees the composer within a second;
  refreshing after the backend finishes shows the completed turn from history.

### 1.6 Session-expiry warning (follow-on to the fix already shipped)

**Evidence**: the mid-use expiry fix (redirect to login) shipped this branch, but the redirect
still interrupts whatever the user was typing.

- Use `keycloak.onTokenExpired` + the refresh-token lifetime to show a "Your session expires in
  2 minutes - continue?" prompt that silently refreshes on click, *before* a send can fail.
  Draft message text survives in component state either way.
- **Exit criteria**: with a short test token lifetime, the prompt appears before expiry and
  clicking it prevents any login redirect mid-conversation.

---

## 2. Carried forward from chat-ui-plan2 (deferred there, sequenced here)

1. **Clickable citations with passage preview** - sources beneath answers become buttons opening
   a side panel/modal with the full retrieved passage, chapter, and score (today they're plain
   text inside the collapsed Routing details).
2. **LangGraph Inspector panel** - a right-side collapsible panel per turn: node execution
   sequence with per-node latency (requires the backend to timestamp its existing SSE status
   events - a small additive change), conditional branches taken, tool calls, state sizes, and
   the MLflow trace ID once tracing lands.
3. **Graph Explorer page** - Mermaid/React Flow rendering of the compiled graph with the actual
   executed path highlighted per selected turn.
4. **Routing Test Lab page** - run the ground-truth suites from the browser; *reuse* the
   existing Streamlit `routing_lab3/dashboard` logic/data rather than rebuilding it.
5. **Observability page** - MLflow traces, latency/token/error trends. Blocked on
   `routing-lab-prod-plan.md`'s observability phase, same as plan1's Loki items.
6. **Thumbs up/down feedback** - only once there's somewhere durable to send it (ties into the
   observability stack; a bare `POST /feedback` into Postgres is an acceptable interim).

---

## 3. Proposed additions (name, purpose, license)

| Addition | Purpose | License |
|---|---|---|
| (none for §1.1-§1.6) | All achievable with the existing stack | - |
| `react-flow` (xyflow) *or* Mermaid | §2.3 Graph Explorer rendering | MIT |
| `@tanstack/react-virtual` (only if needed) | Virtualize very long message lists - measure first; not justified at current conversation sizes | MIT |

Everything else uses already-present dependencies - consistent with the "lightest option that
does the job" rule from plan1 §2.6.

---

## 4. Suggested phasing

1. **Phase A - safety & clarity quick wins (§1.1-§1.4).** Undo-able delete, generated titles,
   humanized progress labels, starter prompts. All small, independent, no new dependencies.
   **Exit criteria**: each item's own criteria above, plus the existing 42-unit/5-e2e/20-backend
   suites still green with new cases for undo and title generation.
2. **Phase B - responsiveness (§1.5, §1.6).** Stop button and session-expiry warning.
3. **Phase C - citations & inspector (§2.1, §2.2).** The user-facing evidence panel first, then
   the developer inspector it shares rendering with; backend adds status-event timestamps.
4. **Phase D - developer pages (§2.3-§2.6).** Graph Explorer, Test Lab (reusing the Streamlit
   dashboard's data contracts), observability page and feedback - sequenced against
   `routing-lab-prod-plan.md`'s infra phases where blocked.

---

## 5. Acceptance checklist

- [ ] A deleted conversation can be restored via Undo within the toast window, and cannot be
      resumed while soft-deleted. (Phase A)
- [ ] Two conversations with identical first messages are visually distinguishable in the
      sidebar without opening them. (Phase A)
- [ ] No raw graph node names appear in the chat surface during a turn. (Phase A)
- [ ] A brand-new user can discover at least one non-appliance topic from the empty state alone.
      (Phase A)
- [ ] A 60-second turn can be abandoned client-side without losing the conversation. (Phase B)
- [ ] An idle session warns before it expires instead of failing/redirecting mid-send. (Phase B)
- [ ] Citations open to their full passage without digging through Routing details. (Phase C)
- [ ] **Regression**: the routing-accuracy ground truth and all existing suites remain green -
      §1.2 adds an LLM call per *conversation* (not per turn) and nothing here touches routing.

---

## 6. Relationship to other documents

- Plan1's open production items (bundle budget, Prettier, runtime Keycloak URL, Grafana/Loki)
  are prerequisites for none of Phase A/B and are not duplicated here.
- Plan2's rejections stand: no Next.js migration, no token-level streaming (the §1.5 Stop button
  is a client-side wait-cancel, deliberately not a server stream), no user-facing model settings.
- The §2 items keep plan2's "keep the chat simple, hide the technical detail until asked"
  principle: everything developer-facing stays behind a collapsed panel or a separate page.
