"""
ChromaDB interface for storing and querying paper embeddings.

Schema (per document):
  id       : arxiv_id  (e.g. "2310.12345")
  document : abstract + method summary (text fed to the embedding model)
  metadata : title, authors, year, url, session_id
  embedding: vector produced by EmbeddingModel
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger(__name__)


def _import_chroma():
    try:
        import chromadb
        return chromadb
    except ImportError as exc:
        raise ImportError(
            "chromadb is not installed. Run: pip install chromadb"
        ) from exc


class VectorDB:
    """
    Manages a single ChromaDB collection called 'papers'.
    Embeddings are provided externally (by EmbeddingModel) so ChromaDB
    is used in 'bring your own embeddings' mode.
    """

    def __init__(
        self,
        persist_path: Path | None = None,
        collection_name: str = config.CHROMA_COLLECTION,
    ) -> None:
        # Read now, not at import time -- see the note in memory/note_db.py.
        self._persist_path = persist_path if persist_path is not None else config.CHROMA_PATH
        self._collection_name = collection_name
        self._client: Any = None
        self._collection: Any = None

    # ------------------------------------------------------------------
    def connect(self) -> None:
        """Open (or create) the persistent ChromaDB store."""
        chromadb = _import_chroma()
        self._client = chromadb.PersistentClient(path=str(self._persist_path))
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "ChromaDB connected: %s  (%d docs)",
            self._persist_path,
            self._collection.count(),
        )

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def add_paper(
        self,
        arxiv_id: str,
        document: str,
        embedding: list[float],
        metadata: dict,
    ) -> None:
        """Insert or update a paper.  Skips silently if ID already exists."""
        if self._collection is None:
            raise RuntimeError("Call VectorDB.connect() first.")

        existing = self._collection.get(ids=[arxiv_id])
        if existing["ids"]:
            logger.debug("Paper %s already in VectorDB, skipping.", arxiv_id)
            return

        self._collection.add(
            ids=[arxiv_id],
            documents=[document],
            embeddings=[embedding],
            metadatas=[metadata],
        )
        logger.debug("Added paper %s to VectorDB.", arxiv_id)

    def add_papers_batch(
        self,
        papers: list[dict],
    ) -> None:
        """
        Batch insert.
        Each dict must have keys: arxiv_id, document, embedding, metadata.
        Skips papers that already exist.
        """
        if self._collection is None:
            raise RuntimeError("Call VectorDB.connect() first.")

        existing_ids: set[str] = set(
            self._collection.get(
                ids=[p["arxiv_id"] for p in papers]
            )["ids"]
        )

        new_papers = [p for p in papers if p["arxiv_id"] not in existing_ids]
        if not new_papers:
            logger.info("All papers already in VectorDB, nothing to add.")
            return

        self._collection.add(
            ids=[p["arxiv_id"] for p in new_papers],
            documents=[p["document"] for p in new_papers],
            embeddings=[p["embedding"] for p in new_papers],
            metadatas=[p["metadata"] for p in new_papers],
        )
        logger.info("Batch-inserted %d papers into VectorDB.", len(new_papers))

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def query(
        self,
        query_embedding: list[float],
        n_results: int = 10,
        where: dict | None = None,
    ) -> list[dict]:
        """
        Return the top-n most similar papers.
        Each result dict: {arxiv_id, document, metadata, distance}
        """
        if self._collection is None:
            raise RuntimeError("Call VectorDB.connect() first.")

        kwargs: dict[str, Any] = {
            "query_embeddings": [query_embedding],
            "n_results": min(n_results, self._collection.count() or 1),
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        results = self._collection.query(**kwargs)

        output = []
        for i, arxiv_id in enumerate(results["ids"][0]):
            output.append({
                "arxiv_id": arxiv_id,
                "document":  results["documents"][0][i],
                "metadata":  results["metadatas"][0][i],
                "distance":  results["distances"][0][i],
            })
        return output

    def get_by_ids(self, arxiv_ids: list[str]) -> list[dict]:
        """Retrieve specific papers by their arxiv IDs."""
        if self._collection is None:
            raise RuntimeError("Call VectorDB.connect() first.")

        results = self._collection.get(
            ids=arxiv_ids,
            include=["documents", "metadatas"],
        )
        output = []
        for i, arxiv_id in enumerate(results["ids"]):
            output.append({
                "arxiv_id": arxiv_id,
                "document":  results["documents"][i],
                "metadata":  results["metadatas"][i],
            })
        return output

    def count(self) -> int:
        if self._collection is None:
            return 0
        return self._collection.count()

    # ------------------------------------------------------------------
    # Duplicate detection
    # ------------------------------------------------------------------

    def find_near_duplicates(
        self,
        embedding: list[float],
        threshold: float = 0.05,  # cosine distance < 0.05 ≈ very similar
    ) -> list[dict]:
        """Return papers that are near-duplicates of the given embedding."""
        results = self.query(query_embedding=embedding, n_results=5)
        return [r for r in results if r["distance"] < threshold]
