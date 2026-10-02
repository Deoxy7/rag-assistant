"""Phase 15: the Streamlit UI — HTTP-only boundary, SSE client, results reader, and the app itself (headless)."""

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import main
from app.api.main import app, llm_client
from tests.test_api import HITS, FakeRetriever, ScriptLLM
from ui import results
from ui.client import APIError, Client, parse_sse

ROOT = Path(__file__).resolve().parents[1]


def test_ui_talks_to_the_system_only_over_http():
    for path in (ROOT / "ui").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            assert not any(n == "app" or n.startswith("app.") for n in names), f"{path.name} imports {names}"


def test_parse_sse_handles_comments_ids_and_multiline_data():
    lines = [": keep-alive", "event: sources", "id: r1", "data: [1,", "data: 2]", "", "event: delta",
             'data: "a\\nb"', "", "", 'data: {"x": 1}']
    assert list(parse_sse(iter(lines))) == [("sources", [1, 2]), ("delta", "a\nb"), ("message", {"x": 1})]


@pytest.fixture
def api(monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(main.state, "retriever", FakeRetriever(HITS))
    monkeypatch.setattr(main.state, "chunk_set_id", 1)
    monkeypatch.setattr(get_settings(), "request_log_enabled", False)
    llm = ScriptLLM(["Net revenue was ", "$23.6 billion [1]."])
    app.dependency_overrides[llm_client] = lambda: llm
    yield Client(http=TestClient(app)), llm
    app.dependency_overrides.clear()


def test_client_streams_sources_deltas_answer_and_times_them(api):
    c, _ = api
    events = list(c.stream("What was AMD's net revenue in 2022?", ["AMD"], [2022], 5))
    assert events[0][0] == "sources" and events[-1][0] == "answer"
    assert "".join(d for e, d in events if e == "delta") == "Net revenue was $23.6 billion [1]."
    assert events[-1][1]["citations"][0]["label"] == "AMD 2022 10-K, p. 43"
    t = c.timings
    assert 0 < t.sources_ms <= t.first_delta_ms <= t.done_ms


def test_client_raises_api_errors_before_and_during_the_stream(api):
    c, llm = api
    with pytest.raises(APIError) as e:
        list(c.stream("x", companies=["NotACompany"]))
    assert e.value.status == 422 and e.value.code == "unknown_company"
    llm.fail_after = 1
    with pytest.raises(APIError) as e:
        list(c.stream("What was revenue?"))
    assert e.value.code == "llm_timeout"


def test_results_reader_on_the_real_phase12_runs():
    runs = results.list_runs()
    names = {r.name for r in runs}
    assert {"gen-v2-rag", "closed-book"} <= names
    assert not any(r.name.startswith("abl-") or "-batch" in r.name for r in runs)
    rag = next(r for r in runs if r.path.name == "20261002T205049Z_gen-v2-rag.json")
    h = results.headline(results.load(rag))
    assert h["hit@5"] == 0.7692 and h["correctness"] == pytest.approx(0.721, abs=0.001)
    assert h["generator"] == "qwen/qwen3.8-27b" and h["config"] == "structure256-hybrid-rr"
    assert runs[results.default_index(runs)].name == "gen-v2-rag"
    cb = next(r for r in runs if r.path.name == "20261002T205101Z_closed-book.json")
    assert results.headline(results.load(cb))["config"] == "no retrieval"
    rows = results.question_rows(results.load(rag))
    assert len(rows) == 61 and set(rows[0]) == set(results.ROW_COLUMNS)


def test_injection_table_matches_the_run_summary():
    run = next(r for r in results.list_runs() if r.path.name == "20261002T222745Z_injection.json")
    data = results.load(run)
    table = results.injection_table(data)
    assert len(table) == 7 and all(r["tried"] == 4 for r in table)
    for cfg in ("v1", "v2", "v2+out", "full"):
        assert sum(r[cfg] for r in table) == data["summary"][cfg]


# --- the Streamlit app, run headless with a fake API client ------------------------------------

class FakeClient:
    base_url = "http://fake"

    def __init__(self):
        from ui.client import StreamTimings
        self.timings = StreamTimings(120.0, 300.0, 900.0)

    def documents(self):
        return [{"doc_key": "AMD_2022_10K", "company": "AMD", "ticker": "AMD", "fiscal_year": 2022, "form": "10-K",
                 "pages": 121, "chunks": 800}]

    def stream(self, question, companies, years, k):
        src = {"n": 1, "chunk_id": 7, "doc_key": "AMD_2022_10K", "company": "AMD", "fiscal_year": 2022,
               "page_number": 43, "page_end": 43, "section": ["Item 7"], "score": 2.5, "text": "Net revenue $23.6B."}
        yield "sources", [src]
        yield "delta", "Net revenue was $23.6 billion [1]."
        yield "answer", {"request_id": "r1", "answer": "Net revenue was $23.6 billion [1].", "refused": False,
                         "refusal_reason": None, "invalid_markers": [], "uncited_sentences": [], "counters": {},
                         "citations": [{"n": 1, "label": "AMD 2022 10-K, p. 43", "chunk_id": 7, "doc_key": "AMD_2022_10K",
                                        "page_number": 43, "page_end": 43, "char_start": 10, "char_end": 29}],
                         "quarantined": [{"chunk_id": 9, "doc_key": "UNTRUSTED_UPLOAD", "page_number": 1,
                                          "signals": ["override"]}],
                         "usage": {"provider": "fake", "model": "fake-1", "input_tokens": 900, "output_tokens": 12,
                                   "cached": False, "truncated": False, "list_usd": 0.0008, "billed_usd": 0.0},
                         "timings_ms": {}, "sources": [src]}

    def stats(self, hours):
        return {"requests": 3, "errors": 0, "cache_hit_rate": 0.0, "list_usd_per_1k_requests": 2.6,
                "stages": {"rerank": {"n": 3, "p50_ms": 100.0, "p95_ms": 120.0}}}

    def page_png(self, chunk_id, page=None, dpi=110):
        raise APIError(404, "page_unavailable", "not in tests")


def test_streamlit_app_renders_answer_citations_and_quarantine(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import ui.client
    monkeypatch.setattr(ui.client, "Client", FakeClient)
    at = AppTest.from_file(str(ROOT / "ui" / "app.py"), default_timeout=30).run()
    assert not at.exception
    assert at.sidebar.caption[0].value.startswith("Searching 1 of 1 filings")
    at.text_input[0].set_value("What was AMD's net revenue in 2022?")
    at.button[0].click().run()
    assert not at.exception
    md = " ".join(m.value for m in at.markdown)
    assert "Net revenue was \\$23.6 billion [1]." in md           # "$" escaped: no LaTeX
    assert any("UNTRUSTED_UPLOAD" in e.value for e in at.error)
    assert any("[1] AMD 2022 10-K, p. 43" in x.label for x in at.expander)
    assert [m.value for m in at.metric][:3] == ["120 ms", "300 ms", "900 ms"]
