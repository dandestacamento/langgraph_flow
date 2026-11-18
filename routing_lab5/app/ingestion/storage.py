"""Document storage for the ingestion pipeline (chat-ui-plan5.md §8).

`LocalDocumentStorage` is the first implementation of the storage-adapter
interface the plan calls for: originals are kept immutably under
`data/documents/<document_id>/v<version>/<filename>`, so a document can
always be reprocessed (re-chunked, re-embedded, re-classified) from its
exact source bytes, and a future Azure Blob / S3 adapter can replace this
class without the ingestion graph changing.

`data/` is gitignored - uploaded knowledge is user data, not repository
content. (`data/staging/` and `data/inbox/` are reserved for the later
watched-folder phase.)
"""

from __future__ import annotations

from pathlib import Path


class LocalDocumentStorage:
    def __init__(self, base_dir: Path) -> None:
        self._documents_dir = base_dir / "documents"
        self._documents_dir.mkdir(parents=True, exist_ok=True)

    def save_original(self, document_id: str, version: int, filename: str, content: bytes) -> str:
        """Stores a document version's original bytes and returns the
        stored path (as a string, for registry/UI display)."""
        directory = self._documents_dir / document_id / f"v{version}"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / Path(filename).name  # strip any client-supplied directories
        path.write_bytes(content)
        return str(path)

    def read_original(self, document_id: str, version: int, filename: str) -> bytes:
        path = self._documents_dir / document_id / f"v{version}" / Path(filename).name
        return path.read_bytes()
