"""Render a cited chunk on its PDF page, with the chunk's blocks highlighted (GET /chunks/{id}/page.png).

The boxes come from the parser's stored block bounding boxes (Phase 2), so the
highlight is exactly the text the citation's character span was built from.
The PDF is located through data/manifest.json and must have the same sha256
as the file that was ingested: a different file under the same name would
put the boxes on the wrong text, so it is refused instead.
"""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import pymupdf

from app.config import REPO_ROOT

DATA = REPO_ROOT / "data"
HIGHLIGHT_STROKE = (0.49, 0.13, 0.81)   # the docs' generation purple
HIGHLIGHT_FILL = (0.95, 0.91, 1.0)


class PageUnavailable(Exception):
    """The PDF for this document isn't on disk, or isn't the file that was ingested."""


@lru_cache(maxsize=1)
def manifest_paths() -> dict[str, Path]:
    docs = json.loads((DATA / "manifest.json").read_text())["documents"]
    return {d["doc_key"]: DATA / d["path"] for d in docs}


@lru_cache(maxsize=32)
def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pdf_for(doc_key: str, expected_sha256: str) -> Path:
    try:
        path = manifest_paths()[doc_key]
    except (FileNotFoundError, KeyError) as exc:
        raise PageUnavailable(f"no PDF listed for {doc_key}") from exc
    if not path.is_file():
        raise PageUnavailable(f"{path.relative_to(REPO_ROOT)} is not on disk (run `make corpus`)")
    if sha256_of(path) != expected_sha256:
        raise PageUnavailable(f"{path.name} differs from the ingested file (sha256 mismatch)")
    return path


def render_highlight(pdf: Path, page_number: int, boxes: list[tuple[float, float, float, float]], dpi: int) -> bytes:
    """PNG of one page (1-based PDF page number) with each box drawn as a translucent rectangle."""
    with pymupdf.open(pdf) as doc:
        page = doc[page_number - 1]
        for x0, y0, x1, y1 in boxes:
            annot = page.add_rect_annot(pymupdf.Rect(x0 - 2, y0 - 2, x1 + 2, y1 + 2))
            annot.set_colors(stroke=HIGHLIGHT_STROKE, fill=HIGHLIGHT_FILL)
            annot.set_opacity(0.45)
            annot.update()
        return page.get_pixmap(dpi=dpi).tobytes("png")
