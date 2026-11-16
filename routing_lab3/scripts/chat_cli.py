"""Phase 0 sanity check (routing-lab3 chat-app plan): exercises
`app.chat.graph.build_chat_graph()` with a handful of hand-written
multi-turn conversations, to validate the condensing step and
conversation flow end to end *before* writing any ground-truth dataset,
test file, or touching a frontend - see
instructions/learnings/routing-lab3-chat-app-plan.md section 8.

For each conversation, every turn shares one `thread_id` (so
`conversation_history` persists via the checkpointer across
`graph.invoke()` calls, the same way `smarthome-csr/app.py` already keys
conversation state); printed output per turn is the user's message, what
the condensing step resolved it to, and the final answer - so a human can
visually confirm follow-ups were understood correctly.

Usage:
    python scripts/chat_cli.py
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import find_dotenv, load_dotenv  # noqa: E402

load_dotenv(find_dotenv())

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from app.cache import enable_llm_cache  # noqa: E402
from app.chat.graph import build_chat_graph  # noqa: E402

enable_llm_cache()

# Hand-written multi-turn conversations covering the main cases the
# condensing step needs to get right: a follow-up resolving a pronoun to
# an established entity, a follow-up switching to a different entity in
# the same domain, and an already-self-contained follow-up that should
# pass through mostly unchanged.
CONVERSATIONS: list[list[str]] = [
    [
        "What is the price of the WM-900 washing machine?",
        "Is it covered under warranty?",
    ],
    [
        "What's the price of the WM-300?",
        "What about the WM-900 instead?",
    ],
    [
        "What does washing machine error E21 mean?",
        "What is the standard refund policy for SmartHome orders?",
    ],
]


def run_conversation(messages: list[str]) -> None:
    graph = build_chat_graph(checkpointer=InMemorySaver())
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    for message in messages:
        output = graph.invoke({"user_message": message}, config=config)
        print(f"  User:               {message}")
        print(f"  Condensed to:       {output['self_contained_question']}")
        print(f"  Final answer:       {output['final_answer']}")
        print()


def main() -> None:
    for i, conversation in enumerate(CONVERSATIONS, start=1):
        print("=" * 78)
        print(f"Conversation {i}")
        print("=" * 78)
        run_conversation(conversation)


if __name__ == "__main__":
    main()
