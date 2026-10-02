"""Phase 4: the real embedding model (bge-small-en-v1.5, pinned revision)."""

import numpy as np
import pytest

from app.embed.embedder import get_embedder


@pytest.fixture(scope="module")
def emb():
    return get_embedder()


def test_vectors_are_384_dimensional_and_unit_length(emb):
    v = emb.embed_documents(["Net revenue grew 19%.", "The cafeteria serves lunch."])
    assert v.shape == (2, 384) and v.dtype == np.float32
    assert np.allclose(np.linalg.norm(v, axis=1), 1.0, atol=1e-5)


def test_similar_meaning_is_closer_than_unrelated_text(emb):
    a, b, c = emb.embed_documents(["Revenue increased in 2022.", "Sales grew last year.", "The cafeteria serves lunch at noon."])
    assert float(a @ b) > float(a @ c) + 0.1   # unit vectors: dot product = cosine similarity


def test_queries_get_the_instruction_and_are_cached(emb):
    before = emb.texts_embedded
    q1 = emb.embed_query("How much did revenue grow?")
    q2 = emb.embed_query("How much did revenue grow?")
    assert emb.texts_embedded == before + 1        # second call served from the cache
    assert np.array_equal(q1, q2)
    plain = emb.embed_documents(["How much did revenue grow?"])[0]
    assert not np.allclose(q1, plain)              # the instruction prefix changes the vector


def test_embedding_is_deterministic_and_batch_independent(emb):
    texts = [f"Item {i}: revenue and margins." for i in range(10)]
    a = emb.embed_documents(texts)
    b = np.vstack([emb.embed_documents([t]) for t in texts])
    assert np.abs(a - b).max() < 1e-5
