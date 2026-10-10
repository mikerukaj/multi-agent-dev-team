"""Memory layer 2: long-term semantic memory stored in Chroma (constitution Principle IV)."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection

from agents.errors import AgentConfigurationError
from config import MEMORY_COLLECTION, Settings


@dataclass(frozen=True)
class MemoryRecord:
    """One piece of agent context stored in long-term memory."""

    kind: str
    """One of: task, plan, thought, observation, result."""

    text: str
    run_id: str
    iteration: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class SemanticMemory:
    """Stores agent context in a Chroma collection and retrieves the most relevant records."""

    def __init__(self, client: ClientAPI, embedding_function: Any = None) -> None:
        self._client = client
        self._embedding_function = embedding_function
        self._collection = self._open_collection()

    @classmethod
    def from_settings(cls, settings: Settings, embedding_function: Any = None) -> "SemanticMemory":
        """Open the store described by ``settings``.

        Uses a Chroma server when ``chroma_host`` is set, otherwise an embedded store at
        ``chroma_path``. ``embedding_function`` defaults to Chroma's built-in model.

        Raises:
            AgentConfigurationError: if Chroma cannot be opened.
        """
        try:
            if settings.chroma_host:
                client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
            else:
                client = chromadb.PersistentClient(path=str(settings.chroma_path))
            return cls(client, embedding_function)
        except Exception as error:
            setting = "CHROMA_HOST/CHROMA_PORT" if settings.chroma_host else "CHROMA_PATH"
            raise AgentConfigurationError(
                f"Could not open Chroma memory store; check {setting}: {error}"
            ) from error

    def add(self, records: list[MemoryRecord]) -> None:
        """Store records. Empty or whitespace-only texts are skipped."""
        records = [record for record in records if record.text.strip()]
        if not records:
            return
        self._collection.add(
            ids=[self._record_id(record) for record in records],
            documents=[record.text for record in records],
            metadatas=[
                {
                    "kind": record.kind,
                    "run_id": record.run_id,
                    "iteration": record.iteration,
                    "created_at": record.created_at,
                }
                for record in records
            ],
        )

    def retrieve(self, query: str, top_k: int, max_distance: float) -> list[str]:
        """Return up to ``top_k`` texts within ``max_distance`` of ``query``, nearest first."""
        count = self._collection.count()
        if count == 0 or not query.strip():
            return []
        result = self._collection.query(query_texts=[query], n_results=min(top_k, count))
        documents = result["documents"][0]
        distances = result["distances"][0]
        return [
            doc
            for doc, distance in zip(documents, distances, strict=True)
            if distance <= max_distance
        ]

    def recent(self, limit: int) -> list[MemoryRecord]:
        """Return the ``limit`` most recently stored records, newest first."""
        stored = self._collection.get(include=["documents", "metadatas"])
        records = [
            MemoryRecord(
                kind=str(metadata["kind"]),
                text=document,
                run_id=str(metadata["run_id"]),
                iteration=int(metadata["iteration"]),
                created_at=str(metadata["created_at"]),
            )
            for document, metadata in zip(stored["documents"], stored["metadatas"], strict=True)
        ]
        records.sort(key=lambda record: record.created_at, reverse=True)
        return records[:limit]

    def count(self) -> int:
        """Return the number of stored records."""
        return self._collection.count()

    def wipe(self) -> int:
        """Delete every record. Returns how many were removed."""
        removed = self._collection.count()
        self._client.delete_collection(MEMORY_COLLECTION)
        self._collection = self._open_collection()
        return removed

    def _open_collection(self) -> Collection:
        if self._embedding_function is None:
            return self._client.get_or_create_collection(MEMORY_COLLECTION)
        return self._client.get_or_create_collection(
            MEMORY_COLLECTION, embedding_function=self._embedding_function
        )

    def _record_id(self, record: MemoryRecord) -> str:
        return f"{record.run_id}:{record.iteration}:{record.kind}:{uuid.uuid4().hex[:12]}"
