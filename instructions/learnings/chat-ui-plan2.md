# Status & decisions (recorded 2026-11-17, implemented on branch `feature/chat-ui-plan2`)

This document below is external redesign advice, written without full knowledge of what
`routing_lab3/frontend` already had. This header records what was done with it, so the advice
isn't re-litigated later.

## Already built before this plan arrived (no action needed)

Conversation memory (LangGraph `PostgresSaver` checkpointer, stable per-conversation thread IDs,
history restored on open), context resolution for follow-ups (the condense step - proven by
`tests/test_chat_api.py`'s follow-up test, not assumed), SSE streaming with per-node progress,
Markdown rendering (sanitized), copy button, retry-on-error, conversation sidebar with new/switch,
mobile layout, auto-scroll, Keycloak auth - see `chat-ui-plan1.md` Phases A-E.

## Implemented from this plan (this branch)

1. **Conversation-meta routing (§3 - the one real behavioral gap this plan found).** The
   always-on condense call now also classifies each message (`is_conversation_meta`, no extra LLM
   call); meta questions ("what was my previous question?") route to a new `answer_from_history`
   graph node that answers from `conversation_history` and never touches knowledge-base RAG. The
   output guardrail still runs on these answers. Verified end-to-end: the exact question from §3's
   screenshot now answers correctly from memory, with no (empty) routing panel shown.
2. **ChatGPT-style composer**: auto-expanding multiline textarea, Enter sends, Shift+Enter
   newline (covered in real Chromium by the e2e suite, not just jsdom).
3. **Regenerate** on the last assistant message (re-asks the turn - in this wrap-the-pipeline
   architecture that's a new turn, not a resample).
4. **Light/dark mode**: class-based Tailwind v4 `@custom-variant`, header toggle, localStorage
   persistence, OS-preference default, themed across every component.
5. **Sidebar management**: search (client-side filter), inline rename (Enter saves/Esc cancels),
   two-step delete - backed by new authenticated `PATCH /threads/{id}` and `DELETE /threads/{id}`
   endpoints; delete removes both the ownership/list record and the checkpointed history
   (`checkpointer.delete_thread`), with the same 403/404 ownership rules as every thread route.

Coverage added with the above: 5 new backend tests (meta-routing answers from history with an
empty routing summary; rename updates the listed title; rename/delete reject other users' threads
and empty titles; delete removes list entry + history), 10 new frontend unit tests, Enter-to-send
exercised in e2e.

## Explicitly rejected, with reasons

- **Next.js migration (§6)**: not justified (the plan's own §7 prompt allows keeping the existing
  stack). The Vite SPA already has auth, tests, CI, and Docker/nginx packaging; SSR solves nothing
  here and would discard all of that.
- **Token-level streaming + Stop button (§2)**: deliberately not implemented - the `check_output`
  secret-leakage guardrail runs *after* answer generation (`app/api/main.py` documents this);
  token streaming would emit unredacted text before the guardrail sees it. Per-node status
  streaming is the guardrail-safe design.
- **User-facing model/temperature settings (§2)**: the routing pipeline is calibrated against the
  228-row ground truth with a fixed model; a user-visible model switch silently invalidates that
  calibration. Reasonable as a developer setting someday, wrong as a product setting.

## Deferred (valid ideas, separate builds)

Thumbs up/down feedback (needs the observability stack to receive it), clickable citations with a
document preview panel, the LangGraph Inspector right-panel, Graph Explorer, Routing Test Lab
(note: `routing_lab3/dashboard` already covers batch evaluation in Streamlit - reuse, don't
duplicate), and the MLflow observability page (§5's four-section navigation). Also still open from
`chat-ui-plan1.md`: size-limit bundle budget, Prettier in CI, runtime-configurable Keycloak URL,
Grafana/Loki deployment.

---

Your current UI is a good starting point for a LangGraph chatbot. From your screenshot, you already have a conversation sidebar, chat bubbles, a message input, and source references.

I would redesign it to look more like ChatGPT, but with additional features specifically for your LangGraph application, especially routing visualization, RAG retrieval, agent execution, and accuracy testing.

The goal should be a modern ChatGPT-style interface with an optional developer/debugging panel.
1. Recommended UI layout

(Image1)

Conceptual layout for your application, showing a ChatGPT-inspired interface with an additional routing indicator.2. UI enhancements I recommend
Feature	Current UI	Recommended enhancement
Sidebar	Basic chat history	Search, rename, delete, group chats
Chat messages	Simple bubbles	ChatGPT-style typography, spacing and Markdown
AI responses	Plain text	Headings, lists, tables, code blocks
Message actions	None visible	Copy, regenerate, thumbs up/down
Input	Single-line field	Auto-expanding multiline input
Streaming	Not visible	Stream responses as tokens arrive
Loading	Not visible	Show "Searching documents" or "Running agent"
Sources	Plain source names	Clickable source citations with document previews
Memory	Appears incomplete	Persistent conversation context
Routing	Not visible	Collapsible routing and agent execution panel
Settings	Minimal	Model selection, temperature, RAG settings
Appearance	Light only	Light/dark theme toggle
Testing	Not visible	Batch evaluation and routing accuracy dashboard

3. Fix conversation memory first
One issue in your screenshot is especially important.

You asked:

"What does washing machine error E21 mean?"

Then:

"What is my previous question?"

The application responded:

"Insufficient information in the knowledge base to answer this question."

That suggests your application is treating a conversation-history question as a knowledge-base retrieval question.

This should be handled by conversation memory, not RAG.

Your router should distinguish at least these types of requests:
Question	Correct route
"What does error E21 mean?"	Technical Agent → RAG
"What was my previous question?"	Conversation History
"How do I fix that error?"	Context Resolver → Technical Agent → RAG
"Summarize our conversation."	Conversation Memory → Summarizer
"What warranty applies to that model?"	Context Resolver → Warranty Agent → RAG

Use LangGraph checkpointers with a persistent backend and stable conversation/thread IDs. Ensure your application passes the previous messages into the graph when processing follow-up questions.

Your third question, "How do I fix that error?", received a relevant response, but that alone does not prove memory is working. It might simply have retrieved the same information.
4. Add a collapsible LangGraph Inspector
This is the feature that would differentiate your application from a normal ChatGPT clone.

I recommend a right-side panel that opens when you click Inspect routing.
(Image2)

Interactive mock-up with simulated execution data. Your real application should populate this panel from LangGraph and MLflow traces.I would also include a Mermaid graph view where executed nodes and edges are highlighted, so you can compare the overall graph architecture against the actual route taken.
5. Suggested navigation
Instead of making everything part of one chat page, create four main sections.

Chat

ChatGPT-style interface for everyday questions, with source citations and optional routing details.



Graph Explorer

Mermaid visualization, active nodes, conditional edges, state changes and tool calls.



Routing Test Lab

Run your 20 ground-truth questions, compare expected and actual routes, and review incorrect answers.



Observability

MLflow traces, latency, token usage, model comparisons, routing accuracy and error trends.



6. What technology should you use?
Since your screenshot shows custom FastAPI backend, I would retain your existing backend and improve the frontend.
Layer	Recommendation
Frontend	Next.js + React + TypeScript
Styling	Tailwind CSS
UI components	shadcn/ui
Chat streaming	Server-Sent Events (SSE)
Backend	Existing FastAPI
Agent orchestration	Existing LangGraph
Conversation memory	LangGraph checkpointer
RAG	Your existing retrieval implementation
Graph visualization	React Flow or Mermaid
Tracing	MLflow
Markdown rendering	react-markdown + remark-gfm
Persistence	SQLite for development, PostgreSQL later

For a ChatGPT-like experience, I would prefer React/Next.js over Streamlit because you have greater control over layout, chat streaming, message interactions, and inspector panels.
7. Prompt for GitHub Copilot
You can paste the following directly into Copilot Chat in VS Code.

I have an existing LangGraph appliance troubleshooting chatbot with a custom FastAPI backend.

I want to redesign the frontend to resemble the modern ChatGPT chat interface while preserving my existing LangGraph backend, routing logic, agents, RAG, and APIs.

First, inspect my current project structure and frontend framework. Reuse the existing technology where practical. If a migration to Next.js is justified, explain the migration plan before making major changes.

Implement the following enhancements:

1. ChatGPT-style user interface

Clean, modern, responsive design

Collapsible left sidebar with conversation history

New conversation, rename, delete, and search

Centered conversation content with comfortable reading width

Distinct user and assistant messages

Markdown rendering, code highlighting, tables, and lists

Copy, regenerate, and feedback buttons

Auto-expanding multiline message input

Enter to send, Shift+Enter for a newline

Streaming responses with a Stop button

Light and dark modes

Mobile-friendly layout

2. Conversation memory

Persist conversation history using LangGraph checkpointing

Use stable thread IDs for each conversation

Restore conversation history when opening an existing chat

Route history-related questions to conversation memory rather than RAG

Resolve contextual follow-up questions using previous messages

Test questions such as "What was my previous question?" and "How do I fix that error?"

3. LangGraph Inspector
Create a collapsible right sidebar showing:

Intent classification

Selected topic, subtopic, and agent

Actual node execution sequence

Conditional branches selected

Tool calls and results

Retrieved RAG documents and scores

State changes

Execution latency

Errors and retries

MLflow trace ID

Use real execution data rather than fabricated traces.

4. RAG citations

Display sources beneath assistant responses

Make citations clickable

Show document name, chapter, and relevant passage

Support viewing retrieved evidence in a modal or side panel

5. Graph Explorer

Render the LangGraph workflow using Mermaid or React Flow

Highlight executed nodes and edges

Allow inspection of individual nodes

Display graph state transitions

6. Routing Test Lab

Load the existing ground-truth test questions

Execute batch routing tests

Compare expected and actual routes

Compare expected and actual answers

Display routing accuracy and answer correctness separately

Allow manual comments and verdicts

Link each test to its execution trace

7. Observability

Integrate MLflow tracing

Display latency, token usage, and errors

Support model and routing strategy comparisons

8. Backend integration

Keep FastAPI as the backend

Implement streaming with SSE

Preserve the existing LangGraph application

Avoid unnecessary rewrites

Keep API keys and secrets on the server

Handle API errors and network failures gracefully

9. Quality

Add tests for conversation persistence, streaming, citations, routing inspection, and batch testing

Maintain responsive performance

Do not break existing functionality

Implement incrementally and test each feature

Start by inspecting my current application and proposing the updated component structure. Then implement the ChatGPT-style layout, conversation memory, and message streaming before building the advanced debugging panels.

8. My recommended implementation priority
For your application, I would implement these in this order:
1. Conversation memory — fix the previous-question issue visible in your screenshot.
2. ChatGPT-style layout — modern sidebar, message area, input, Markdown and dark mode.
3. Streaming responses — make conversations feel interactive.
4. Clickable RAG citations — inspect the actual evidence behind answers.
5. LangGraph Inspector — understand routing, tool execution, and state.
6. Routing Test Lab — connect your 20 ground-truth questions and evaluation reports.
7. MLflow dashboard and Graph Explorer — investigate failures and compare routing strategies.
The key design principle is to keep the normal chat interface simple and hide technical details until you choose to inspect them.

That way, you have a clean ChatGPT-like experience for users and a powerful LangGraph debugging environment for yourself.