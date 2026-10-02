"""`make ingest`: parse → chunk → store → embed → index, for one chunking configuration.

    python -m app.ingest.pipeline                                   # settings defaults
    python -m app.ingest.pipeline --strategy fixed --size 128 --overlap 16

Idempotent: re-running skips unchanged documents, existing chunks and existing
embeddings, so it can be interrupted and resumed. Each document is written in
its own transaction.
"""

import argparse
import sys
import time
from dataclasses import dataclass, field

import numpy as np
import psycopg

from app.config import get_settings
from app.embed.embedder import Embedder, get_embedder, model_key
from app.ingest.chunking import get_chunker
from app.ingest.models import ParsedDocument
from app.ingest.parse_corpus import load_or_parse, manifest_documents
from app.store import repository as repo
from app.store.db import connect
from app.store.migrate import apply_migrations


@dataclass
class IngestReport:
    chunk_set_id: int = 0
    documents: dict[str, str] = field(default_factory=dict)   # doc_key -> action
    chunks_inserted: int = 0
    embeddings_reused: int = 0
    embeddings_computed: int = 0
    index_name: str = ""
    index_created: bool = False
    seconds: dict[str, float] = field(default_factory=dict)


def ingest(conn: psycopg.Connection, docs: list[tuple[dict, ParsedDocument]], strategy: str, size: int,
           overlap: int, embedder: Embedder) -> IngestReport:
    s = get_settings()
    report = IngestReport()
    timer = time.perf_counter
    chunker = get_chunker(strategy, size, overlap)
    tokenizer = model_key(s.embedding_model, s.embedding_model_revision)

    with conn.transaction():
        report.chunk_set_id = repo.get_or_create_chunk_set(conn, strategy, size, overlap, tokenizer)

    t = timer()
    chunk_seconds = 0.0
    for entry, doc in docs:
        with conn.transaction():
            doc_id, action = repo.upsert_document(conn, entry, doc)
            report.documents[entry["doc_key"]] = action
            if not repo.has_chunks(conn, report.chunk_set_id, doc_id):
                c0 = timer()
                chunks = chunker.chunk(doc)
                chunk_seconds += timer() - c0
                report.chunks_inserted += repo.insert_chunks(conn, report.chunk_set_id, doc_id, chunks)
    report.seconds["chunk"] = round(chunk_seconds, 1)
    report.seconds["store_documents_and_chunks"] = round(timer() - t - chunk_seconds, 1)

    t = timer()
    with conn.transaction():
        report.embeddings_reused = repo.reuse_embeddings(conn, report.chunk_set_id, embedder.key)
    missing = repo.chunks_missing_embeddings(conn, report.chunk_set_id, embedder.key)
    # Identical texts are embedded once: 599 of 7,411 structure chunks repeat
    # another chunk word for word (boilerplate copied from one year to the next).
    by_text: dict[str, list[int]] = {}
    for chunk_id, text in missing:
        by_text.setdefault(text, []).append(chunk_id)
    texts = list(by_text)
    batch = 512  # commit every 512 distinct texts so an interrupted run keeps its progress
    for start in range(0, len(texts), batch):
        group = texts[start:start + batch]
        vectors = embedder.embed_documents(group)
        report.embeddings_computed += len(group)
        ids = [cid for text in group for cid in by_text[text]]
        rows = [vec for text, vec in zip(group, vectors) for _ in by_text[text]]
        with conn.transaction():
            stored = repo.insert_embeddings(conn, report.chunk_set_id, embedder.key, ids, np.array(rows))
        report.embeddings_reused += stored - len(group)
    report.seconds["embed"] = round(timer() - t, 1)

    t = timer()
    with conn.transaction():
        report.index_name, report.index_created = repo.ensure_hnsw_index(conn, report.chunk_set_id,
                                                                          embedder.key, embedder.dims)
    # Fresh statistics so the planner knows the new row counts.
    conn.execute("ANALYZE chunks")
    conn.execute("ANALYZE embeddings")
    conn.commit()
    report.seconds["index"] = round(timer() - t, 1)
    return report


def main(argv: list[str]) -> int:
    s = get_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", default=s.chunk_strategy)
    parser.add_argument("--size", type=int, default=s.chunk_size)
    parser.add_argument("--overlap", type=int, default=s.chunk_overlap)
    args = parser.parse_args(argv)

    started = time.perf_counter()
    t = time.perf_counter()
    docs = [(entry, load_or_parse(entry)) for entry in manifest_documents()]
    parse_seconds = round(time.perf_counter() - t, 1)
    t = time.perf_counter()
    embedder = get_embedder()
    load_seconds = round(time.perf_counter() - t, 1)
    with connect() as conn:
        apply_migrations(conn)
        report = ingest(conn, docs, args.strategy, args.size, args.overlap, embedder)
        counts = conn.execute("""SELECT (SELECT count(*) FROM documents), (SELECT count(*) FROM pages),
                                        (SELECT count(*) FROM blocks),
                                        (SELECT count(*) FROM chunks WHERE chunk_set_id = %(s)s),
                                        (SELECT count(*) FROM embeddings WHERE chunk_set_id = %(s)s)""",
                              {"s": report.chunk_set_id}).fetchone()
        sizes = repo.relation_sizes(conn)

    print(f"chunk set {report.chunk_set_id}: {args.strategy} size={args.size} overlap={args.overlap} "
          f"| model {embedder.key} on {embedder.device}")
    print("documents: " + ", ".join(f"{k}={v}" for k, v in report.documents.items()))
    print(f"chunks inserted {report.chunks_inserted} | embeddings reused {report.embeddings_reused} "
          f"computed {report.embeddings_computed} | index {report.index_name} "
          f"({'created' if report.index_created else 'existed'})")
    print(f"rows: documents={counts[0]} pages={counts[1]} blocks={counts[2]} chunks(set)={counts[3]} embeddings(set)={counts[4]}")
    print(f"seconds: parse/load-cache={parse_seconds} model-load={load_seconds} "
          + " ".join(f"{k}={v}" for k, v in report.seconds.items())
          + f" total={round(time.perf_counter() - started, 1)}")
    print("sizes: " + ", ".join(f"{name}={size / 1e6:.1f}MB" for name, size in sizes[:8]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
