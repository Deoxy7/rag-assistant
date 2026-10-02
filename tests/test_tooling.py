"""Unit tests for the docs tooling in scripts/ (no database, no renderer needed)."""

import pytest

from scripts import collect_cards, where_it_sits

ARCH = """flowchart TB
    subgraph online["Online"]
        api["FastAPI"]:::io
        pg[("Postgres")]:::store
    end
    legend["Legend: grey = storage"]:::legend
    api -->|query| pg
"""


# --- where_it_sits ----------------------------------------------------------

def test_node_ids_finds_nodes_and_subgraphs_but_not_edges():
    assert where_it_sits.node_ids(ARCH) == {"online", "api", "pg", "legend"}


def test_highlight_adds_a_style_line_per_id_and_extends_the_legend():
    out = where_it_sits.highlight(ARCH, ["pg"])
    assert f"style pg {where_it_sits.HIGHLIGHT_STYLE}" in out
    assert "style api" not in out
    assert where_it_sits.LEGEND_SUFFIX in out


def test_highlight_rejects_unknown_ids_so_typos_fail_the_build():
    with pytest.raises(ValueError, match="unknown node id"):
        where_it_sits.highlight(ARCH, ["postgres"])


def test_highlight_requires_exactly_one_legend():
    with pytest.raises(ValueError, match="legend"):
        where_it_sits.highlight(ARCH.replace("legend[", "key["), ["pg"])


def test_read_table_parses_and_rejects_malformed_lines(tmp_path):
    good = tmp_path / "good.tsv"
    good.write_text("# comment\n03\tpg\n09\tvec, pg\n")
    assert where_it_sits.read_table(good) == {"03": ["pg"], "09": ["vec", "pg"]}

    bad = tmp_path / "bad.tsv"
    bad.write_text("3 pg\n")
    with pytest.raises(ValueError, match="expected"):
        where_it_sits.read_table(bad)


# --- collect_cards ----------------------------------------------------------

CARD_DOC = """# Some doc
<!-- card:start id=15 -->
#### Decision: Postgres (rejected: Pinecone)
See [doc 09](09-vector-search.md) and [OWASP](https://owasp.org) and [above](#top).
Log in [progress](../PROGRESS.md).
```text
[not a link](inside-code.md)
```
<!-- card:end -->
Text between cards.
<!-- card:start id=x-colima -->
#### Decision: Colima (rejected: Docker Desktop)
Body.
<!-- card:end -->
"""


def test_extract_cards_returns_ids_and_bodies_in_order():
    cards = collect_cards.extract_cards(CARD_DOC, "doc.md")
    assert [card_id for card_id, _ in cards] == ["15", "x-colima"]
    assert cards[0][1].startswith("#### Decision: Postgres")


def test_marker_mentioned_inline_is_not_a_card():
    text = "Cards are wrapped in `<!-- card:start id=… -->` markers.\n" + CARD_DOC
    assert [card_id for card_id, _ in collect_cards.extract_cards(text, "doc.md")] == ["15", "x-colima"]


def test_unterminated_card_is_an_error():
    with pytest.raises(ValueError, match="card:start"):
        collect_cards.extract_cards("<!-- card:start id=1 -->\n#### Decision: x\n", "doc.md")


def test_card_must_start_with_a_decision_heading():
    with pytest.raises(ValueError, match="must begin"):
        collect_cards.extract_cards("<!-- card:start id=1 -->\nhello\n<!-- card:end -->", "doc.md")


def test_unknown_mandatory_number_is_an_error():
    with pytest.raises(ValueError, match="not in the mandatory list"):
        collect_cards.extract_cards("<!-- card:start id=99 -->\n#### Decision: x\n<!-- card:end -->", "doc.md")


def test_rewrite_links_prefixes_relative_targets_only_outside_code():
    body = collect_cards.extract_cards(CARD_DOC, "doc.md")[0][1]
    out = collect_cards.rewrite_links(body)
    assert "](../09-vector-search.md)" in out
    assert "](../../PROGRESS.md)" in out  # already-relative-upward links move down a level too
    assert "](https://owasp.org)" in out
    assert "](#top)" in out
    assert "[not a link](inside-code.md)" in out
