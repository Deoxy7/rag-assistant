"""Parse every corpus PDF once and cache the result as JSON.

    python -m app.ingest.parse_corpus          # parse what's missing or stale, print a summary
    python -m app.ingest.parse_corpus --force  # re-parse everything

A cached file is reused only if it was produced from the same PDF bytes
(source sha256) by the same parser version; otherwise it is rebuilt, so a
parser change can never be silently mixed with old output.
"""

import json
import sys
from pathlib import Path

from app.config import REPO_ROOT
from app.ingest.models import ParsedDocument
from app.ingest.pdf_parser import PARSER_VERSION, parse_pdf

DATA = REPO_ROOT / "data"
PARSED = DATA / "parsed"


def manifest_documents() -> list[dict]:
    return json.loads((DATA / "manifest.json").read_text())["documents"]


def cache_path(doc_key: str) -> Path:
    return PARSED / f"{doc_key}.json"


def load_or_parse(entry: dict, force: bool = False) -> ParsedDocument:
    path = cache_path(entry["doc_key"])
    if path.exists() and not force:
        cached = json.loads(path.read_text())
        if cached["parser_version"] == PARSER_VERSION and cached["source_sha256"] == entry["sha256"]:
            return ParsedDocument.from_json(cached)
    parsed = parse_pdf(DATA / entry["path"], entry["doc_key"], entry["sha256"])
    PARSED.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(parsed.to_json()))
    return parsed


def main(argv: list[str]) -> int:
    force = "--force" in argv
    print(f"{'document':18s} {'pages':>5s} {'blocks':>6s} {'heads':>5s} {'tables':>6s} {'edge-':>6s} {'pgno-':>5s} {'2-col':>5s} {'chars':>9s} {'secs':>5s}")
    for entry in manifest_documents():
        doc = load_or_parse(entry, force=force)
        s = doc.stats
        print(f"{doc.doc_key:18s} {s['pages']:5d} {s['blocks']:6d} {s.get('headings', 0):5d} {s.get('tables', 0):6d} "
              f"{s.get('edge_blocks_removed', 0):6d} {s.get('page_number_blocks_removed', 0):5d} {s.get('two_column_pages', 0):5d} {s['chars']:9d} {s['parse_seconds']:5.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
