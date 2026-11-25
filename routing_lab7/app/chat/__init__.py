"""Chat-application layer (routing-lab6): wraps the existing, unmodified
single-question `app.graph.build_graph()` pipeline with multi-turn
conversation memory, per
instructions/learnings/routing-lab6-chat-app-plan.md.

See `state.py` for the conversation state shape, `condense.py` for the
follow-up-resolution step, and `graph.py` for how they're wired together.
"""
