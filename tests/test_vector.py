"""Phase 5: vector retrieval on synthetic vectors in rag_test.

1,560 random 16-dimensional unit vectors: 1,500 for "BigCo 2022" and 60 for
"SmallCo 2021" (3.8% of rows), so a SmallCo filter is selective enough to show
the post-filter recall cliff. Random vectors make exact answers easy to compute
with numpy.
"""

import numpy as np
import pytest

from app.ingest.chunking import Chunk
from app.ingest.models import Block, Page, ParsedDocument
from app.retrieve.types import Filters
from app.retrieve.vector import VectorRetriever
from app.store import repository as repo

DIMS = 16


class VecEmbedder:
    key = "random-test@00000000"
    dims = DIMS

    def __init__(self, queries):
        self.queries = queries

    def embed_query(self, text):
        return self.queries[text]


def insert_doc(db, key, company, year, n, rng, chunk_set_id):
    texts = [f"{key} chunk {i}" for i in range(n)]
    canonical = "\n\n".join(texts)
    offsets, pos = [], 0
    for t in texts:
        offsets.append((pos, pos + len(t)))
        pos += len(t) + 2
    doc = ParsedDocument(key, "0" * 64, "test", canonical, [Page(1, 0, len(canonical), 612, 792, "body")],
                         [Block(0, 1, 0, len(canonical), "text", 0, ("S",), (0, 0, 1, 1), canonical)])
    entry = {"doc_key": key, "company": company, "ticker": "X", "fiscal_year": year, "form": "10-K"}
    doc_id, _ = repo.upsert_document(db, entry, doc)
    chunks = [Chunk(i, s, e, 1, 1, ("S",), 3, t) for i, ((s, e), t) in enumerate(zip(offsets, texts))]
    repo.insert_chunks(db, chunk_set_id, doc_id, chunks)
    ids = [r[0] for r in db.execute("SELECT id FROM chunks WHERE document_id = %s ORDER BY chunk_index", (doc_id,))]
    vecs = rng.normal(size=(n, DIMS)).astype(np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    repo.insert_embeddings(db, chunk_set_id, VecEmbedder.key, ids, vecs)
    return dict(zip(ids, vecs))


@pytest.fixture
def corpus(db):
    rng = np.random.default_rng(7)
    with db.transaction():
        set_id = repo.get_or_create_chunk_set(db, "fixed", 8, 1, "t")
        big = insert_doc(db, "BIG", "BigCo", 2022, 1500, rng, set_id)
        small = insert_doc(db, "SMALL", "SmallCo", 2021, 60, rng, set_id)
        repo.ensure_hnsw_index(db, set_id, VecEmbedder.key, DIMS)
    db.execute("ANALYZE embeddings")
    db.commit()
    queries = {f"q{i}": v / np.linalg.norm(v) for i, v in enumerate(rng.normal(size=(30, DIMS)).astype(np.float32))}
    return set_id, {**big, **small}, set(small), queries


def brute_force(vectors: dict, q, k, allowed=None):
    ids = [i for i in vectors if allowed is None or i in allowed]
    return [i for i in sorted(ids, key=lambda i: -float(vectors[i] @ q))][:k]


def test_exact_mode_equals_numpy_brute_force(db, corpus):
    set_id, vectors, _, queries = corpus
    r = VectorRetriever(VecEmbedder(queries), set_id, filter_mode="exact")
    for name, q in queries.items():
        hits = r.search(db, name, k=10)
        assert [h.chunk_id for h in hits] == brute_force(vectors, q, 10)
        assert hits[0].score == pytest.approx(float(vectors[hits[0].chunk_id] @ q), abs=1e-5)
        assert [h.rank for h in hits] == list(range(1, 11))


def test_hnsw_recall_is_high_with_a_generous_ef_search(db, corpus):
    set_id, vectors, _, queries = corpus
    r = VectorRetriever(VecEmbedder(queries), set_id, ef_search=200, filter_mode="post")
    overlap = [len({h.chunk_id for h in r.search(db, n, k=10)} & set(brute_force(vectors, q, 10))) / 10
               for n, q in queries.items()]
    assert np.mean(overlap) >= 0.9


def test_filters_restrict_results(db, corpus):
    set_id, vectors, small, queries = corpus
    hits = VectorRetriever(VecEmbedder(queries), set_id).search(db, "q0", k=10, filters=Filters(companies=("SmallCo",)))
    assert len(hits) == 10 and all(h.company == "SmallCo" and h.chunk_id in small for h in hits)


def test_post_filter_recall_cliff_and_iterative_fix(db, corpus):
    set_id, vectors, small, queries = corpus
    db.prepare_threshold = None  # a cached plan would ignore enable_sort (T-026)
    f = Filters(companies=("SmallCo",))
    counts = {}
    for mode in ("post", "iterative"):
        r = VectorRetriever(VecEmbedder(queries), set_id, ef_search=40, filter_mode=mode)
        n = []
        for name, q in queries.items():
            with db.transaction():
                db.execute("SET LOCAL enable_sort = off")  # force the HNSW path, as on a big table
                db.execute(f"SET LOCAL hnsw.iterative_scan = {'relaxed_order' if mode == 'iterative' else 'off'}")
                db.execute("SET LOCAL hnsw.ef_search = 40")
                rows = db.execute(r.query_sql(f, exact=False), {"q": repo.vector_literal(q), "k": 10,
                                                                "companies": ["SmallCo"], "years": []}).fetchall()
            n.append(len(rows))
        counts[mode] = np.mean(n)
    assert counts["post"] < 5      # ~40 candidates × 3.8% ≈ 1.5 survive the filter
    assert counts["iterative"] == 10


def test_settings_do_not_leak_between_searches(db, corpus):
    # Regression for T-025: on a non-autocommit connection SET LOCAL survives
    # until the outer transaction ends, so every search must set both values.
    set_id, _, _, queries = corpus
    emb = VecEmbedder(queries)
    db.execute("SELECT 1")  # open an outer transaction: searches now run in savepoints inside it
    VectorRetriever(emb, set_id, filter_mode="iterative", ef_search=99).search(db, "q0", k=3)
    VectorRetriever(emb, set_id, filter_mode="post", ef_search=41).search(db, "q0", k=3)
    assert db.execute("SHOW hnsw.iterative_scan").fetchone()[0] == "off"
    assert db.execute("SHOW hnsw.ef_search").fetchone()[0] == "41"


def test_generic_plan_still_uses_the_partial_index_because_set_and_model_are_literals(db, corpus):
    set_id, _, _, queries = corpus
    r = VectorRetriever(VecEmbedder(queries), set_id, filter_mode="post")
    literal_sql = r.query_sql(Filters(), exact=False).as_string(db).replace("%(q)s", "$1").replace("%(k)s", "$2")
    param_sql = literal_sql.replace(f"e.chunk_set_id = {set_id}", "e.chunk_set_id = $3")
    db.execute("SET plan_cache_mode = force_generic_plan")
    db.execute("SET enable_sort = off")
    db.execute(f"PREPARE lit(vector, int) AS {literal_sql}")
    db.execute(f"PREPARE par(vector, int, int) AS {param_sql}")
    q = repo.vector_literal(queries["q0"])
    lit = "\n".join(row[0] for row in db.execute(f"EXPLAIN EXECUTE lit('{q}', 5)"))
    par = "\n".join(row[0] for row in db.execute(f"EXPLAIN EXECUTE par('{q}', 5, {set_id})"))
    index = repo.hnsw_index_name(set_id, VecEmbedder.key)
    assert index in lit       # literal predicate: provably matches the partial index
    assert index not in par   # $3 predicate: the generic plan cannot prove it
    db.rollback()
