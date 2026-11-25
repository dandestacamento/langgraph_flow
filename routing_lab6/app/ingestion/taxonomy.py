"""Shared, persistent additions to the curated knowledge taxonomy."""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

from app.config import PROJECT_ROOT, TOPIC_SUBTOPICS

_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


class TaxonomyStore:
    def __init__(self, conn_string: str | None = None, path: Path | None = None) -> None:
        self._conn_string = conn_string
        self._path = path or PROJECT_ROOT / "data" / "taxonomy.db"
        if conn_string:
            import psycopg

            with psycopg.connect(conn_string) as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS knowledge_taxonomy "
                    "(topic TEXT NOT NULL, subtopic TEXT NOT NULL, PRIMARY KEY (topic, subtopic))"
                )
        else:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self._path) as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS knowledge_taxonomy "
                    "(topic TEXT NOT NULL, subtopic TEXT NOT NULL, PRIMARY KEY (topic, subtopic))"
                )

    def get(self) -> dict[str, list[str]]:
        if self._conn_string:
            import psycopg

            with psycopg.connect(self._conn_string) as conn:
                rows = conn.execute("SELECT topic, subtopic FROM knowledge_taxonomy ORDER BY topic, subtopic").fetchall()
        else:
            with sqlite3.connect(self._path) as conn:
                rows = conn.execute("SELECT topic, subtopic FROM knowledge_taxonomy ORDER BY topic, subtopic").fetchall()
        result = {topic: list(subtopics) for topic, subtopics in TOPIC_SUBTOPICS.items()}
        for topic, subtopic in rows:
            subtopics = result.setdefault(topic, [])
            if subtopic not in subtopics:
                subtopics.append(subtopic)
        return result

    def add(self, topic: str, subtopic: str) -> None:
        if not _IDENTIFIER.fullmatch(topic) or not _IDENTIFIER.fullmatch(subtopic):
            raise ValueError("Topic and subtopic must be lowercase identifiers (letters, digits and underscores; 64 characters maximum).")
        if self._conn_string:
            import psycopg

            with psycopg.connect(self._conn_string) as conn:
                conn.execute(
                    "INSERT INTO knowledge_taxonomy (topic, subtopic) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (topic, subtopic),
                )
        else:
            with sqlite3.connect(self._path) as conn:
                conn.execute(
                    "INSERT INTO knowledge_taxonomy (topic, subtopic) VALUES (?, ?) ON CONFLICT DO NOTHING",
                    (topic, subtopic),
                )


_store: TaxonomyStore | None = None


def taxonomy_store() -> TaxonomyStore:
    global _store
    if _store is None:
        _store = TaxonomyStore(os.environ.get("CHAT_DB_URL"))
    return _store
