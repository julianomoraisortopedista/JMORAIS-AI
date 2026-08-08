from __future__ import annotations

import os
import re
from typing import Any

import chromadb
import numpy as np

from jmoraIs.config import ROOT_DIR


class ChromaVectorStore:
    def __init__(self, persist_directory: str | None = None):
        db_path = persist_directory or os.path.join(ROOT_DIR, ".chroma")
        self.client = chromadb.PersistentClient(path=db_path)
        self.collection = self.client.get_or_create_collection(name="scientific_articles")

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [token.lower() for token in re.findall(r"[a-zA-Z0-9]+", text or "")]

    @classmethod
    def embed_text(cls, text: str, dimension: int = 32) -> list[float]:
        tokens = cls._tokenize(text)
        if not tokens:
            return [0.0 for _ in range(dimension)]

        vector = np.zeros(dimension, dtype=float)
        for token in tokens:
            idx = abs(hash(token)) % dimension
            vector[idx] += 1.0

        norm = np.linalg.norm(vector)
        if norm == 0:
            return [0.0 for _ in range(dimension)]
        return (vector / norm).tolist()

    def add_document(self, doc_id: str, text: str, metadata: dict[str, Any]) -> None:
        self.collection.add(
            ids=[doc_id],
            documents=[text],
            metadatas=[metadata],
            embeddings=[self.embed_text(text)],
        )

    def semantic_search(self, query: str, limit: int = 5, where: dict[str, Any] | None = None) -> dict[str, Any]:
        query_embedding = self.embed_text(query)
        return self.collection.query(
            query_embeddings=[query_embedding],
            n_results=limit,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
