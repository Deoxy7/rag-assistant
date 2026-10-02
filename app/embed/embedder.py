"""Embedding client: batching, normalisation, device choice and a query cache.

Documents and queries are embedded differently on purpose: bge v1.5 expects a
short instruction in front of *queries* only (see Settings.query_instruction).
"""

from functools import lru_cache

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

from app.config import get_settings


def model_key(model: str, revision: str) -> str:
    """How a model is identified in the database: name@first-8-of-revision."""
    return f"{model}@{revision[:8]}"


class Embedder:
    def __init__(self, model: str, revision: str, cache_dir, device: str, batch_size: int, query_instruction: str):
        if device == "auto":
            device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.device = device
        self.batch_size = batch_size
        self.query_instruction = query_instruction
        self.key = model_key(model, revision)
        self.model = SentenceTransformer(model, revision=revision, cache_folder=str(cache_dir), device=device)
        self.dims = self.model.get_embedding_dimension()
        self.texts_embedded = 0  # counts real model calls; tests use it to prove the cache works
        self._query_cache = lru_cache(maxsize=4096)(self._embed_query_uncached)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        """Unit-length float32 vectors, one row per text, in input order."""
        if not texts:
            return np.zeros((0, self.dims), dtype=np.float32)
        self.texts_embedded += len(texts)
        # normalize_embeddings=True divides each vector by its length, so cosine
        # similarity and inner product become the same number (card #13).
        return self.model.encode(texts, batch_size=self.batch_size, normalize_embeddings=True,
                                 convert_to_numpy=True, show_progress_bar=False).astype(np.float32)

    def _embed_query_uncached(self, text: str) -> tuple[float, ...]:
        self.texts_embedded += 1
        vec = self.model.encode([self.query_instruction + text], normalize_embeddings=True,
                                convert_to_numpy=True, show_progress_bar=False)[0]
        return tuple(float(x) for x in vec)  # hashable, so lru_cache can store it

    def embed_query(self, text: str) -> np.ndarray:
        """Query vector (instruction-prefixed); repeated queries are served from memory."""
        return np.asarray(self._query_cache(text), dtype=np.float32)


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    s = get_settings()
    return Embedder(s.embedding_model, s.embedding_model_revision, s.model_cache_dir,
                    s.embedding_device, s.embedding_batch_size, s.query_instruction)
