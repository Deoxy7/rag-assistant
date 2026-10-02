"""Chunk the whole corpus with every strategy × size and report the shapes.

    python -m app.ingest.chunk_corpus            # 3 strategies × sizes 128/256/510 (overlap = size/8)
    python -m app.ingest.chunk_corpus --check    # also verify every chunk's offsets

Nothing is stored here — Phase 4 ingests chunks into Postgres. This exists to
measure chunk counts and size distributions before paying to embed them.
"""

import statistics
import sys
import time

from app.ingest.chunking import CHUNKERS, get_chunker
from app.ingest.parse_corpus import load_or_parse, manifest_documents

SIZES = (128, 256, 510)  # 510 = bge-small's 512 minus [CLS] and [SEP]


def percentile(values: list[int], q: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def main(argv: list[str]) -> int:
    check = "--check" in argv
    docs = [load_or_parse(e) for e in manifest_documents()]
    print(f"{'strategy':9s} {'size':>4s} {'ovl':>3s} {'chunks':>6s} {'p5':>4s} {'p50':>4s} {'p95':>4s} {'max':>4s} "
          f"{'<25%':>5s} {'x-page':>6s} {'tokens':>8s} {'secs':>5s}")
    for strategy in CHUNKERS:
        for size in SIZES:
            overlap = size // 8
            chunker = get_chunker(strategy, size, overlap)
            started = time.perf_counter()
            chunks = [c for d in docs for c in chunker.chunk(d)]
            secs = time.perf_counter() - started
            if check:
                for d in docs:
                    for c in chunker.chunk(d):
                        assert d.text[c.char_start:c.char_end] == c.text
            tokens = [c.token_count for c in chunks]
            tiny = sum(t < size / 4 for t in tokens)
            cross = sum(c.page_end != c.page_number for c in chunks)
            print(f"{strategy:9s} {size:4d} {overlap:3d} {len(chunks):6d} {percentile(tokens, .05):4d} "
                  f"{statistics.median(tokens):4.0f} {percentile(tokens, .95):4d} {max(tokens):4d} "
                  f"{tiny:5d} {cross:6d} {sum(tokens):8d} {secs:5.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
