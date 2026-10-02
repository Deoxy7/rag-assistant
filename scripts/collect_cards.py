"""Mirror every Decision Card from docs/ into docs/interview/09-tradeoff-cards.md.

A Decision Card lives in the doc of the phase that made the decision, wrapped
in markers so it can be found mechanically:

    <!-- card:start id=15 -->
    #### Decision: Postgres + pgvector  (rejected: ...)
    ...
    <!-- card:end -->

`id` is the item number (1-42) from the mandatory list below, or `x-<slug>` for
an extra card. 09-tradeoff-cards.md is rebuilt from these blocks, so the two
copies cannot drift apart. Run with --check to exit 1 if 09 is out of date.
"""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"
TARGET = DOCS / "interview" / "09-tradeoff-cards.md"

# The 42 mandatory cards (addendum section C) and the phase each is written in.
MANDATORY: dict[int, tuple[str, int]] = {
    1: ("RAG vs fine-tuning vs long-context stuffing vs plain prompting", 0),
    2: ("A structured corpus (10-K / protocols / policies) vs a toy corpus", 1),
    3: ("Abstention policy: answer with weak evidence vs refuse", 9),
    4: ("PyMuPDF vs pdfplumber vs unstructured.io vs OCR vs LLM-based parsing", 2),
    5: ("Store page_number + char_start + char_end vs text only", 2),
    6: ("Batch vs incremental ingest; updated and deleted documents", 4),
    7: ("Deduplication strategy; near-duplicate boilerplate", 4),
    8: ("Fixed-size vs recursive-character vs structure-aware vs semantic chunking", 3),
    9: ("Chunk size and overlap: the quality/cost curve", 3),
    10: ("Chunk-level vs sentence-level vs parent-document retrieval", 3),
    11: ("Local open embedding model vs API embeddings", 4),
    12: ("Embedding dimension: 384 vs 768 vs 1536", 4),
    13: ("Normalisation and distance metric: cosine vs inner product vs L2", 4),
    14: ("Re-embedding cost when the model is upgraded", 4),
    15: ("Postgres + pgvector vs Pinecone / Qdrant / Weaviate / Milvus / FAISS / Elasticsearch", 0),
    16: ("HNSW vs IVFFlat vs exact scan; m, ef_construction, ef_search", 4),
    17: ("Vectors in the same table vs a separate table", 4),
    18: ("Metadata filtering: pre-filter vs post-filter, and the recall cliff", 5),
    19: ("Quantisation (scalar / binary): when it is worth the recall loss", 5),
    20: ("Dense-only vs sparse-only vs hybrid retrieval", 7),
    21: ("Postgres FTS vs Elasticsearch/OpenSearch BM25 vs SPLADE", 6),
    22: ("RRF vs weighted-score fusion vs learned fusion", 7),
    23: ("The RRF k constant: what it actually controls", 7),
    24: ("Top-k at each stage: over-retrieve, then narrow", 8),
    25: ("Cross-encoder vs bi-encoder vs ColBERT vs LLM-as-reranker vs no rerank", 8),
    26: ("Rerank depth N: the quality/latency curve", 8),
    27: ("Context packing order and token budget (lost-in-the-middle)", 9),
    28: ("Citation granularity: document vs chunk vs sentence vs character span", 9),
    29: ("Prompt design for grounding; temperature; structured output", 9),
    30: ("FastAPI vs Flask vs Django vs Express", 10),
    31: ("SSE vs WebSockets vs polling vs plain JSON", 10),
    32: ("Async vs sync; where CPU-bound work goes", 10),
    33: ("Caching: exact-match vs semantic vs embedding cache; invalidation", 13),
    34: ("LangChain vs plain Python vs LlamaIndex", 0),
    35: ("Self-built eval harness vs RAGAS vs TruLens vs DeepEval", 11),
    36: ("Retrieval metrics: recall@k vs precision@k vs MRR vs nDCG", 11),
    37: ("LLM-as-judge vs human labels vs ROUGE/BLEU; judge bias and variance", 11),
    38: ("Golden set construction: size, difficulty mix, unanswerables, leakage", 11),
    39: ("Docker Compose vs managed Postgres vs bare metal", 0),
    40: ("Multi-tenancy / document ACLs: row-level security vs filter vs separate indexes", 14),
    41: ("Prompt-injection defences; where trust boundaries sit", 14),
    42: ("Streamlit vs React/TypeScript for the demo", 15),
}

# Markers count only when they stand alone on a line, so a doc can *mention*
# the marker syntax in prose or code without opening a phantom card.
CARD = re.compile(
    r"^<!-- card:start id=(?P<id>\d+|x-[a-z0-9-]+) -->\n(?P<body>.*?)\n<!-- card:end -->$",
    re.DOTALL | re.MULTILINE,
)
START = re.compile(r"^<!-- card:start id=([^ ]+) -->$", re.MULTILINE)
FENCE = re.compile(r"^(```|~~~)")
LINK_TARGET = re.compile(r"(\]\()([^)\s]+)(\))")


def extract_cards(text: str, source: str) -> list[tuple[str, str]]:
    """Return [(id, body)] for every card in one markdown file, in file order."""
    starts = START.findall(text)
    cards = [(m.group("id"), m.group("body")) for m in CARD.finditer(text)]
    if len(starts) != len(cards):
        raise ValueError(f"{source}: {len(starts)} card:start marker(s) but {len(cards)} complete card(s)")
    for card_id, body in cards:
        if not body.lstrip().startswith("#### Decision:"):
            raise ValueError(f"{source}: card {card_id} must begin with '#### Decision:'")
        if not card_id.startswith("x-") and int(card_id) not in MANDATORY:
            raise ValueError(f"{source}: card id {card_id} is not in the mandatory list (use x-<slug>)")
    return cards


def rewrite_links(body: str) -> str:
    """Re-point relative links from docs/ to docs/interview/ by prefixing '../'.

    Absolute URLs, in-page anchors and anything inside fenced code are left alone.
    """
    out, in_fence = [], False
    for line in body.split("\n"):
        if FENCE.match(line.strip()):
            in_fence = not in_fence
        elif not in_fence:
            line = LINK_TARGET.sub(_prefix, line)
        out.append(line)
    return "\n".join(out)


def _prefix(m: re.Match) -> str:
    target = m.group(2)
    # Every relative target moves one level deeper — including ones that already
    # start with '../' (docs/../PROGRESS.md must become docs/interview/../../PROGRESS.md).
    if re.match(r"^(https?:|mailto:|#|/)", target):
        return m.group(0)
    return f"{m.group(1)}../{target}{m.group(3)}"


def collect() -> list[tuple[str, Path, str]]:
    """All cards in docs/NN-*.md as (id, source path, body); ids must be unique."""
    found: list[tuple[str, Path, str]] = []
    seen: dict[str, Path] = {}
    for md in sorted(DOCS.glob("[0-9][0-9]-*.md")):
        for card_id, body in extract_cards(md.read_text(), md.name):
            if card_id in seen:
                raise ValueError(f"card {card_id} appears in both {seen[card_id].name} and {md.name}")
            seen[card_id] = md
            found.append((card_id, md, body))
    return found


def build() -> str:
    cards = collect()
    by_id = {card_id: (path, body) for card_id, path, body in cards}

    lines = [
        "# 09 — Trade-off cards: every Decision Card in one place",
        "",
        "**Status:** generated by `make cards` from the Decision Cards inside `docs/NN-*.md`.",
        "Do not edit this file by hand — edit the card in its source doc, then run `make cards`.",
        "",
        "Use this as a single-sitting revision document: read a card, close it, and say the",
        "*interview script* and the answers to the *follow-ups* out loud.",
        "",
        "## Coverage of the 42 mandatory cards",
        "",
        "| # | Decision | Phase | Written in |",
        "|---|---|---|---|",
    ]
    for number, (title, phase) in MANDATORY.items():
        if str(number) in by_id:
            path = by_id[str(number)][0]
            where = f"✅ [{path.stem}](../{path.name})"
        else:
            where = "not yet written"
        lines.append(f"| {number} | {title} | {phase} | {where} |")

    lines += ["", "## Mandatory cards", ""]
    for number in MANDATORY:
        if str(number) in by_id:
            path, body = by_id[str(number)]
            lines += [f"### Card {number} — from [{path.stem}](../{path.name})", "", rewrite_links(body), ""]

    extras = [(card_id, path, body) for card_id, path, body in cards if card_id.startswith("x-")]
    lines += ["## Extra cards (decisions beyond the mandatory 42)", ""]
    if not extras:
        lines += ["None yet.", ""]
    for card_id, path, body in extras:
        lines += [f"### Card {card_id} — from [{path.stem}](../{path.name})", "", rewrite_links(body), ""]

    return "\n".join(lines).rstrip("\n") + "\n"


def main(argv: list[str]) -> int:
    text = build()
    if "--check" in argv:
        if not TARGET.exists() or TARGET.read_text() != text:
            print(f"{TARGET.relative_to(REPO)} is out of date — run `make cards`", file=sys.stderr)
            return 1
        return 0
    TARGET.write_text(text)
    count = text.count("\n### Card ")
    print(f"wrote {TARGET.relative_to(REPO)} with {count} card(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
