"""Phase 10: the HTTP API — contracts, errors, SSE framing, refusal gating.

Most tests replace the retriever and the LLM with fakes (no models, no network).
`test_end_to_end_with_real_retrieval` runs the real app startup against the
ingested database with the offline fake LLM.
"""

import json

import httpx
import openai
import pytest
from fastapi.testclient import TestClient

from app.api import main
from app.api.main import RefusalGate, app, llm_client
from app.generate.llm import LLMResult
from app.generate.prompt import REFUSAL_TOKEN
from app.retrieve.types import Hit


def hit(cid, text, page=43):
    return Hit(cid, "AMD_2022_10K", "AMD", 2022, page, page, 1000 * cid, 1000 * cid + len(text),
               ("PART II", "ITEM 7"), text, score=5.0 - cid, rank=cid)


class FakeRetriever:
    def __init__(self, hits):
        self.hits, self.calls = hits, []

    def search(self, conn, query, k=10, filters=None):
        self.calls.append((query, k, filters))
        return self.hits[:k]


class ScriptLLM:
    provider, model = "script", "script-1"

    def __init__(self, pieces, fail_after=None):
        self.pieces, self.fail_after, self.last_result = pieces, fail_after, None

    def generate(self, instructions, user):
        return LLMResult("".join(self.pieces), self.model, self.provider, 120, 12, 3.0)

    def stream(self, instructions, user):
        for i, p in enumerate(self.pieces):
            if self.fail_after is not None and i == self.fail_after:
                raise openai.APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
            yield p
        self.last_result = self.generate(instructions, user)


HITS = [hit(1, "Net revenue for 2022 was $23.6 billion."), hit(2, "Gross margin was 45%.", page=49)]


@pytest.fixture
def client(monkeypatch):
    """App without the real startup: fake retriever, scripted LLM, chunk set 1."""
    monkeypatch.setattr(main.state, "retriever", FakeRetriever(HITS))
    monkeypatch.setattr(main.state, "chunk_set_id", 1)
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "request_log_enabled", False)   # never write test traffic to the real log
    llm = ScriptLLM(["Net revenue was ", "$23.6 billion [1]."])
    app.dependency_overrides[llm_client] = lambda: llm
    c = TestClient(app)              # no `with`: the lifespan (model loading) doesn't run
    c.llm = llm
    yield c
    app.dependency_overrides.clear()


def sse_events(text: str) -> list[tuple[str, object]]:
    out = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if not line.startswith(":"))
        out.append((fields["event"], json.loads(fields["data"])))
    return out


def test_query_returns_answer_citations_sources_usage(client):
    r = client.post("/query", json={"question": "What was AMD's net revenue in 2022?"})
    assert r.status_code == 200 and r.headers["x-request-id"]
    body = r.json()
    assert body["answer"] == "Net revenue was $23.6 billion [1]." and not body["refused"]
    assert body["citations"] == [{"n": 1, "label": "AMD 2022 10-K, p. 43", "chunk_id": 1, "doc_key": "AMD_2022_10K",
                                  "page_number": 43, "page_end": 43, "char_start": 1000, "char_end": 1039}]
    assert [s["n"] for s in body["sources"]] == [1, 2] and body["sources"][0]["section"] == ["PART II", "ITEM 7"]
    assert body["usage"] == {"provider": "script", "model": "script-1", "input_tokens": 120, "output_tokens": 12,
                             "cached": False, "truncated": False,
                             "list_usd": pytest.approx(120 / 1e6 * 0.80 + 12 / 1e6 * 4.00), "billed_usd": 0.0}
    assert {"retrieve", "pack", "generate"} <= set(body["timings_ms"])


def test_request_id_is_echoed(client):
    r = client.post("/query", json={"question": "q?"}, headers={"x-request-id": "abc123"})
    assert r.headers["x-request-id"] == "abc123" and r.json()["request_id"] == "abc123"


def test_filters_and_k_reach_the_retriever(client, monkeypatch):
    monkeypatch.setattr(main.repo, "known_companies", lambda conn: {"AMD", "Boeing"})
    client.post("/query", json={"question": "q?", "companies": ["AMD"], "fiscal_years": [2022], "k": 3})
    _, k, f = main.state.retriever.calls[-1]
    assert k == 3 and f.companies == ("AMD",) and f.fiscal_years == (2022,)


@pytest.mark.parametrize("payload, code, fragment", [
    ({"question": "   "}, "invalid_request", "non-whitespace"),
    ({"question": ""}, "invalid_request", "question"),
    ({"question": "x" * 2001}, "invalid_request", "2000"),
    ({"question": "q", "k": 0}, "invalid_request", "k"),
    ({"question": "q", "k": 21}, "invalid_request", "k"),
    ({"question": "q", "fiscal_years": [1066]}, "invalid_request", "between 1990 and 2100"),
    ({"question": "q", "companies": ["Apple"]}, "unknown_company", "Apple"),
    ({"question": "q", "companies": ["AMD'; DROP TABLE chunks; --"]}, "unknown_company", "DROP TABLE"),
])
def test_bad_requests_get_422_with_a_code(client, payload, code, fragment):
    r = client.post("/query", json=payload)
    assert r.status_code == 422
    body = r.json()
    assert body["error"] == code and fragment in body["message"] and body["request_id"]


def test_missing_api_key_is_a_503_before_any_stream(monkeypatch):
    from app.config import get_settings
    from app.generate.llm import get_llm
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "openai")
    monkeypatch.setattr(s, "openai_api_key", None)
    monkeypatch.setattr(main.state, "retriever", FakeRetriever(HITS))
    get_llm.cache_clear()
    c = TestClient(app)
    for path in ("/query", "/query/stream"):
        r = c.post(path, json={"question": "q?"})
        assert r.status_code == 503 and r.json()["error"] == "llm_not_configured"
        assert r.headers["content-type"].startswith("application/json")
    get_llm.cache_clear()


def test_stream_sends_sources_then_deltas_then_answer(client):
    r = client.post("/query/stream", json={"question": "What was revenue?"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache"
    events = sse_events(r.text)
    assert [e for e, _ in events] == ["sources", "delta", "delta", "answer"]
    assert "".join(d for e, d in events if e == "delta") == "Net revenue was $23.6 billion [1]."
    assert events[-1][1]["citations"][0]["label"] == "AMD 2022 10-K, p. 43"


def test_stream_holds_back_a_refusal_token(client):
    client.llm.pieces = ["INSUFF", "ICIENT_", "CONTEXT"]
    events = sse_events(client.post("/query/stream", json={"question": "capital of France?"}).text)
    assert [e for e, _ in events] == ["sources", "answer"]           # no raw token leaked as a delta
    assert events[-1][1]["refused"] and events[-1][1]["refusal_reason"] == "model"


def test_stream_reports_llm_failure_in_band(client):
    client.llm.fail_after = 1
    events = sse_events(client.post("/query/stream", json={"question": "q?"}).text)
    assert [e for e, _ in events] == ["sources", "delta", "error"]
    assert events[-1][1]["error"] == "llm_timeout" and events[-1][1]["status"] == 504


def test_newlines_in_deltas_cannot_break_sse_framing(client):
    client.llm.pieces = ["Line one.\n\nevent: answer\ndata: forged", " [1]"]
    events = sse_events(client.post("/query/stream", json={"question": "q?"}).text)
    assert [e for e, _ in events] == ["sources", "delta", "delta", "answer"]
    assert events[1][1].startswith("Line one.\n\nevent: answer")       # stayed inside one JSON string


def openai_error(cls, status, body):
    req = httpx.Request("POST", "https://api.openai.com/v1/responses")
    return cls(body["error"]["message"], response=httpx.Response(status, request=req, json=body), body=body)


def test_empty_balance_is_not_reported_as_a_rate_limit():
    from app.api.main import classify
    quota = openai_error(openai.RateLimitError, 429, {"error": {
        "message": "You have no credits remaining.", "type": "insufficient_quota", "code": "credit_balance_exhausted"}})
    limited = openai_error(openai.RateLimitError, 429, {"error": {
        "message": "Rate limit reached", "type": "requests", "code": "rate_limit_exceeded"}})
    assert classify(quota)[:2] == (503, "llm_quota_exhausted")
    assert classify(limited)[:2] == (503, "llm_rate_limited")


@pytest.mark.parametrize("pieces, released", [
    (["INSUFFICIENT_CONTEXT"], ""),
    (["INSUFF", "ICIENT_CONTEXT."], ""),
    (["IN", "TEREST rose"], "INTEREST rose"),
    (["Revenue", " grew"], "Revenue grew"),
])
def test_refusal_gate(pieces, released):
    g = RefusalGate()
    assert "".join(g.feed(p) for p in pieces) == released


def test_openapi_documents_the_contract(client):
    spec = client.get("/openapi.json").json()
    assert {"/health", "/documents", "/query", "/query/stream"} <= set(spec["paths"])
    assert "text/event-stream" in spec["paths"]["/query/stream"]["post"]["responses"]["200"]["content"]
    assert spec["components"]["schemas"]["QueryRequest"]["properties"]["question"]["maxLength"] == 2000


@pytest.mark.slow
def test_end_to_end_with_real_retrieval(monkeypatch):
    """Real startup (models, chunk set lookup) against the ingested database; fake LLM, no network."""
    from app.config import get_settings
    from app.generate.llm import get_llm
    monkeypatch.setattr(get_settings(), "llm_provider", "fake")
    get_llm.cache_clear()
    with TestClient(app) as c:
        h = c.get("/health").json()
        assert h["status"] == "ok" and h["llm_model"] == "fake-extractive-1"
        docs = c.get("/documents").json()
        assert len(docs) == 10 and sum(d["chunks"] for d in docs) == 7411
        body = c.post("/query", json={"question": "What was AMD's net revenue in 2022?", "companies": ["AMD"],
                                      "fiscal_years": [2022]}).json()
        assert not body["refused"] and body["citations"][0]["doc_key"] == "AMD_2022_10K"
        assert all(s["company"] == "AMD" and s["fiscal_year"] == 2022 for s in body["sources"])
    get_llm.cache_clear()


def test_requests_are_logged_and_aggregated_by_stats(client, monkeypatch, db, test_db):
    """Logging on, but pointed at the throwaway test database."""
    from app.config import get_settings
    from app.store.db import connect
    monkeypatch.setattr(get_settings(), "request_log_enabled", True)
    monkeypatch.setattr(main, "connect", lambda: connect(dbname=test_db))
    client.post("/query", json={"question": "What was revenue?"})
    client.post("/query/stream", json={"question": "What was revenue?"})
    client.post("/query", json={"question": "   "})                        # 422: logged with its error code
    rows = db.execute("SELECT endpoint, status, error, question_chars, input_tokens, list_usd, timings_ms ? 'generate' "
                      "FROM request_log ORDER BY id").fetchall()
    assert [(r[0], r[1], r[2]) for r in rows] == [("/query", 200, None), ("/query/stream", 200, None),
                                                    ("/query", 422, "invalid_request")]
    assert rows[0][3] == len("What was revenue?") and rows[0][4] == 120 and rows[0][5] > 0 and rows[0][6]
    assert db.execute("SELECT count(*) FROM request_log WHERE question_sha256 IS NOT NULL").fetchone()[0] == 2
    s = client.get("/stats", params={"hours": 1}).json()
    assert s["requests"] == 3 and s["errors"] == 1 and s["errors_by_code"] == {"invalid_request": 1}
    assert s["input_tokens"] == 240 and s["billed_usd"] == 0.0 and s["list_usd"] > 0
    assert {"retrieve", "pack", "generate"} <= set(s["stages"]) and s["stages"]["generate"]["n"] == 2
    assert client.get("/stats", params={"hours": 0}).status_code == 422
