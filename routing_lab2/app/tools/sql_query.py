"""SQL query tool (Level 8 - tool selection and execution): queries the
structured CSV reference data under `knowledge_base/` (e.g.
`appliances/washing_machines/specifications.csv`) via an in-memory
SQLite database, for exact-value lookups that Markdown-chapter RAG
retrieval handles poorly or can't answer at all - e.g. `price_aud` is a
CSV-only column with no prose equivalent in any chapter, by design, so a
price question can only be answered correctly via this tool.

Uses the Python standard library's `sqlite3` (no new dependency) rather
than DuckDB/pandas, since the CSVs here are a handful of rows each - a
full SQL engine dependency isn't warranted at this scale.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from app.config import KNOWLEDGE_BASE_DIR

_SPECIFICATIONS_TABLE = "specifications"


def get_specifications_csv_path(topic: str, subtopic: str) -> Path | None:
    """The `specifications.csv` path for a (topic, subtopic) pair, or
    `None` if that subtopic has no structured specifications data (e.g.
    every `customer_support` subtopic - its reference data is prose
    policy, not per-model specs)."""
    path = KNOWLEDGE_BASE_DIR / topic / subtopic / "specifications.csv"
    return path if path.exists() else None


def get_specifications_schema(topic: str, subtopic: str) -> list[str] | None:
    """Column names of that (topic, subtopic)'s `specifications.csv`
    header row, or `None` if it doesn't have one - used to tell the Tool
    Router's LLM call what columns it can query without guessing."""
    path = get_specifications_csv_path(topic, subtopic)
    if path is None:
        return None
    with path.open(encoding="utf-8", newline="") as f:
        return next(csv.reader(f))


def _infer_column_type(values: list[str]) -> str:
    """SQLite column type declaration for a CSV column, inferred from its
    values - needed so numeric columns get INTEGER/REAL affinity (and
    therefore numeric, not lexicographic, ordering/comparison in SQL);
    without this, declaring every column with no type at all would give
    it BLOB/no affinity, storing values as the literal TEXT the CSV
    reader produced, and `ORDER BY price_aud` would then sort "1499"
    before "699" as strings."""
    try:
        for v in values:
            int(v)
        return "INTEGER"
    except ValueError:
        pass
    try:
        for v in values:
            float(v)
        return "REAL"
    except ValueError:
        return "TEXT"


def run_sql_query(query: str, topic: str, subtopic: str) -> list[dict]:
    """Load `specifications.csv` for (topic, subtopic) into an in-memory
    SQLite table named `specifications` and run `query` against it,
    returning one dict per result row. Raises `ValueError` if that
    subtopic has no specifications data, the query isn't a read-only
    `SELECT`, or `query` is otherwise invalid SQL (`sqlite3.Error`).

    The read-only guard is defense-in-depth, not a response to an
    observed problem: `query` is LLM-generated (via `tool_router`'s
    structured output) and executed against an in-memory, per-call,
    throwaway SQLite database built fresh from this process's own CSV, so
    the actual blast radius of a non-SELECT statement here is already
    minimal - but cheap to rule out entirely rather than rely on that,
    consistent with the identical "LLM-authored SQL executed directly"
    pattern flagged as worth hardening in
    instructions/learnings/routing-lab2-learnings.md / rag-krish-learnings.md."""
    path = get_specifications_csv_path(topic, subtopic)
    if path is None:
        raise ValueError(f"No specifications.csv for {topic}/{subtopic} - sql_query isn't applicable here.")

    stripped = query.strip()
    if not stripped.lower().startswith(("select", "with")):
        raise ValueError(
            f"Only read-only SELECT (or WITH ... SELECT) queries are allowed - got: {query!r}"
        )
    # Reject any statement that would modify the schema/data even if it
    # somehow passed the SELECT/WITH prefix check (e.g. a WITH clause
    # followed by an INSERT) or is chained via a semicolon - sqlite3's
    # Cursor.execute() only runs a single statement, but this is
    # belt-and-suspenders against a crafted multi-statement string.
    forbidden = ("insert", "update", "delete", "drop", "alter", "attach", "pragma", "create")
    if any(f" {word} " in f" {stripped.lower()} " for word in forbidden):
        raise ValueError(f"Query contains a disallowed (non-read-only) keyword: {query!r}")

    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"{path} has no data rows.")

    connection = sqlite3.connect(":memory:")
    try:
        columns = list(rows[0].keys())
        column_types = {c: _infer_column_type([row[c] for row in rows]) for c in columns}
        column_defs = ", ".join(f"{c} {column_types[c]}" for c in columns)
        connection.execute(f"CREATE TABLE {_SPECIFICATIONS_TABLE} ({column_defs})")
        connection.executemany(
            f"INSERT INTO {_SPECIFICATIONS_TABLE} VALUES ({', '.join('?' for _ in columns)})",
            [tuple(row[c] for c in columns) for row in rows],
        )
        cursor = connection.execute(query)
        result_columns = [d[0] for d in cursor.description]
        return [dict(zip(result_columns, row)) for row in cursor.fetchall()]
    finally:
        connection.close()
