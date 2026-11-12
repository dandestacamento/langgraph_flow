"""Pytest configuration: load OPENAI_API_KEY and friends from .env so the
LLM-backed router/agent tests can run outside a shell that already has them
exported."""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()
