"""The docs rules in CLAUDE.md, enforced by `make test` instead of by memory.

- every image a doc embeds exists and is non-empty
- every relative link between docs resolves
- every embedded diagram is followed by its ASCII twin, and twins fit in 100 columns
- every diagram source has been rendered from its *current* text (manifest hash)
- every numbered doc declares a status line
- 09-tradeoff-cards.md is an exact mirror of the cards in the docs
- every interview question id appears in the question map
"""

import hashlib
import re
from pathlib import Path

import pytest

from scripts import collect_cards, where_it_sits

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"
SRC = DOCS / "diagrams" / "src"
OUT = DOCS / "diagrams" / "out"

MD_FILES = sorted(DOCS.rglob("*.md"))
NUMBERED_DOCS = [p for p in MD_FILES if re.match(r"\d\d-", p.name)]
INTERVIEW = DOCS / "interview"

IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")
DIAGRAM_EMBED = re.compile(r"!\[[^\]]*\]\((?:\.\./)*diagrams/out/[^)]+\.png\)")


def rel(paths):
    return [str(p.relative_to(REPO)) for p in paths]


def prose(text: str) -> str:
    """Text with fenced code blocks and inline code removed (examples are not links)."""
    text = re.sub(r"^(```|~~~).*?^\1", "", text, flags=re.MULTILINE | re.DOTALL)
    return re.sub(r"`[^`\n]*`", "", text)


@pytest.mark.parametrize("md", MD_FILES, ids=rel(MD_FILES))
def test_every_embedded_image_exists_and_is_not_empty(md):
    for target in IMAGE.findall(prose(md.read_text())):
        path = (md.parent / target).resolve()
        assert path.is_file(), f"{md.name} embeds a missing image: {target}"
        assert path.stat().st_size > 0, f"{md.name} embeds an empty image: {target}"


@pytest.mark.parametrize("md", MD_FILES, ids=rel(MD_FILES))
def test_every_relative_link_resolves(md):
    for target in LINK.findall(prose(md.read_text())):
        if re.match(r"^(https?:|mailto:|#)", target):
            continue
        path = (md.parent / target.split("#", 1)[0]).resolve()
        assert path.exists(), f"{md.name} links to a missing file: {target}"


@pytest.mark.parametrize("md", MD_FILES, ids=rel(MD_FILES))
def test_every_embedded_diagram_is_followed_by_an_ascii_twin(md):
    lines = md.read_text().splitlines()
    for i, line in enumerate(lines):
        if DIAGRAM_EMBED.search(line):
            following = [l for l in lines[i + 1 : i + 4] if l.strip()]
            assert following and following[0].startswith("<details>"), (
                f"{md.name}:{i + 1}: diagram image must be followed by a <details> ASCII version"
            )


@pytest.mark.parametrize("md", MD_FILES, ids=rel(MD_FILES))
def test_ascii_twins_fit_in_100_columns(md):
    # Only the code blocks inside <details> are ASCII diagrams; prose answers
    # in "Check yourself" blocks are ordinary wrapped text.
    for block in re.findall(r"<details>.*?</details>", md.read_text(), flags=re.DOTALL):
        for art in re.findall(r"^```text\n(.*?)^```", block, flags=re.DOTALL | re.MULTILINE):
            for line in art.splitlines():
                assert len(line) <= 100, f"{md.name}: ASCII line is {len(line)} chars: {line[:40]}…"


@pytest.mark.parametrize("md", NUMBERED_DOCS, ids=rel(NUMBERED_DOCS))
def test_numbered_docs_declare_a_status(md):
    head = "\n".join(md.read_text().splitlines()[:6])
    assert "**Status:**" in head, f"{md.name}: missing a **Status:** line near the top"


def manifest() -> dict[str, dict[str, str]]:
    rows = (OUT / "manifest.tsv").read_text().splitlines()
    header = rows[0].split("\t")
    return {r.split("\t")[0]: dict(zip(header, r.split("\t"))) for r in rows[1:]}


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_every_hand_written_diagram_is_rendered_from_its_current_source():
    rendered = manifest()
    for src in sorted(SRC.glob("*.mmd")) + sorted(SRC.glob("*.dot")):
        row = rendered.get(src.stem)
        assert row, f"{src.name} has never been rendered — run `make diagrams`"
        assert row["sha256"] == sha256(src.read_text()), f"{src.name} changed since it was rendered — run `make diagrams`"


def test_every_where_it_sits_diagram_is_current():
    rendered = manifest()
    for name, text in where_it_sits.generate_all().items():
        stem = name.removesuffix(".mmd")
        assert stem in rendered, f"{stem} has never been rendered — run `make diagrams`"
        assert rendered[stem]["sha256"] == sha256(text), f"{stem} is stale — run `make diagrams`"


def test_every_rendered_diagram_has_both_outputs():
    for name in manifest():
        for ext in ("svg", "png"):
            f = OUT / f"{name}.{ext}"
            assert f.is_file() and f.stat().st_size > 0, f"missing or empty {f.name}"


def test_every_rendered_png_is_used_by_some_doc():
    used = "\n".join(p.read_text() for p in MD_FILES)
    for png in sorted(OUT.glob("*.png")):
        assert f"diagrams/out/{png.name}" in used, f"{png.name} is not embedded in any doc"


def test_tradeoff_cards_file_mirrors_the_docs():
    target = collect_cards.TARGET
    assert target.read_text() == collect_cards.build(), "09-tradeoff-cards.md is stale — run `make cards`"


def test_every_interview_question_is_in_the_question_map():
    question_map = (INTERVIEW / "02-question-map.md").read_text()
    for md in sorted(INTERVIEW.glob("*.md")):
        if md.name == "02-question-map.md":
            continue
        for qid in re.findall(r"\*\*ID:\*\* (P\d+-\d+)", md.read_text()):
            assert qid in question_map, f"{md.name}: question {qid} is missing from 02-question-map.md"


def test_question_ids_are_unique():
    seen: dict[str, str] = {}
    for md in sorted(INTERVIEW.glob("*.md")):
        if md.name == "02-question-map.md":
            continue
        for qid in re.findall(r"\*\*ID:\*\* (P\d+-\d+)", md.read_text()):
            assert qid not in seen, f"{qid} used in both {seen[qid]} and {md.name}"
            seen[qid] = md.name
