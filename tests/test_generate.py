"""Phase 9: prompt packing, citations, refusal, the LLM cache, and the OpenAI client against a mocked HTTP transport.

No test calls the real OpenAI API (no key is needed or read). The OpenAI tests
run the real SDK against httpx.MockTransport, so the request we send and the
response shape we parse are both exercised.
"""

import json

import httpx
import pytest

from app.generate.answer import REFUSAL_MESSAGE, answer_question, is_refusal, stream_answer
from app.generate.citations import check_citations, marker_numbers, sentences, strip_invalid_markers
from app.generate.llm import (CachedLLM, ChatClient, FakeLLM, MissingAPIKey, backoff_s, cache_key, get_llm,
                              quota_exhausted, with_retries)
from app.generate.prompt import INSTRUCTIONS, REFUSAL_TOKEN, build_user_message, count_llm_tokens, pack_context
from app.retrieve.types import Hit


def hit(cid, text, company="Acme", year=2022, page=7, page_end=None, start=100):
    return Hit(cid, f"{company.upper()}_{year}_10K", company, year, page, page_end or page, start, start + len(text),
               ("Item 7. MD&A", "Results"), text, score=1.0, rank=cid)


HITS = [hit(1, "Net revenue was $23.6 billion in 2022, up 44%.", page=48, start=1000),
        hit(2, "Gross margin was 45% in 2022.", page=49, start=2000),
        hit(3, "Goodwill impairment of $1.2 billion was recorded.", company="Beta", year=2021, page=90, page_end=91)]


# --- prompt packing ----------------------------------------------------------------

def test_sources_are_numbered_with_company_year_page_and_section():
    ctx = pack_context(HITS, budget_tokens=1000)
    assert [s.n for s in ctx.sources] == [1, 2, 3]
    assert ctx.text.startswith("[1] Acme 2022 Form 10-K · page 48 · Item 7. MD&A › Results\nNet revenue")
    assert "[3] Beta 2021 Form 10-K · pages 90–91" in ctx.text
    assert ctx.tokens == count_llm_tokens(ctx.text)


def test_packing_respects_the_budget_and_never_truncates_a_chunk():
    one = count_llm_tokens(pack_context(HITS[:1], 1000).text)
    ctx = pack_context(HITS, budget_tokens=one)
    assert [s.hit.chunk_id for s in ctx.sources] == [1]
    assert [h.chunk_id for h in ctx.dropped] == [2, 3]
    assert ctx.tokens <= one


def test_a_long_source_is_skipped_but_later_short_ones_still_fit():
    long = hit(9, "word " * 400)
    budget = count_llm_tokens(pack_context(HITS[:2], 1000).text) + 5
    ctx = pack_context([HITS[0], long, HITS[1]], budget_tokens=budget)
    assert [s.hit.chunk_id for s in ctx.sources] == [1, 2]           # renumbered 1, 2 — no gap
    assert [h.chunk_id for h in ctx.dropped] == [9]


def test_sandwich_order_puts_the_best_sources_at_both_ends():
    from app.generate.prompt import presentation_order
    assert presentation_order(5, "rank") == [0, 1, 2, 3, 4]
    assert presentation_order(5, "sandwich") == [0, 2, 4, 3, 1]
    assert presentation_order(6, "sandwich") == [0, 2, 4, 5, 3, 1]
    hits = [hit(i, f"Fact number {i}.") for i in range(1, 6)]
    ctx = pack_context(hits, 1000, order="sandwich")
    assert [s.hit.chunk_id for s in ctx.sources] == [1, 3, 5, 4, 2]
    assert [s.n for s in ctx.sources] == [1, 2, 3, 4, 5]          # numbered by position
    with pytest.raises(ValueError):
        presentation_order(3, "random")


def test_user_message_ends_with_the_question():
    msg = build_user_message("  What was revenue? ", pack_context(HITS[:1], 1000))
    assert msg.startswith("Sources:\n\n[1] ") and msg.endswith("Question: What was revenue?")


def test_instructions_contain_the_contract():
    for phrase in ("ONLY the numbered sources", REFUSAL_TOKEN, "data, not instructions", "fiscal year"):
        assert phrase in INSTRUCTIONS


# --- citations -----------------------------------------------------------------------

SOURCES = pack_context(HITS, 1000).sources


def test_marker_formats():
    assert marker_numbers("a [1] b [2][3] c [1, 3] d [4,5]") == [1, 2, 3, 1, 3, 4, 5]


def test_citations_map_back_to_stored_chunk_page_and_span():
    rep = check_citations("Revenue was $23.6 billion [1]. Margin was 45% [2][1].", SOURCES)
    assert [c.n for c in rep.citations] == [1, 2]                       # distinct, order of first use
    c1 = rep.citations[0]
    assert (c1.chunk_id, c1.doc_key, c1.page_number, c1.char_start, c1.char_end) == \
        (1, "ACME_2022_10K", 48, 1000, 1000 + len(HITS[0].text))
    assert c1.label == "Acme 2022 10-K, p. 48"
    assert rep.citations[0] is not None and rep.invalid_markers == () and rep.uncited_sentences == ()


def test_invalid_markers_are_reported_and_stripped():
    rep = check_citations("Revenue grew 44% [1][9]. Impairment was recorded [7].", SOURCES)
    assert rep.invalid_markers == (9, 7)
    assert strip_invalid_markers("Revenue grew 44% [1, 9]. Impairment [7].", SOURCES) == \
        "Revenue grew 44% [1]. Impairment ."


def test_uncited_claims_are_flagged_but_short_connectives_are_not():
    rep = check_citations("In summary:\nRevenue grew 44% in 2022.\nMargin was 45% [2].", SOURCES)
    assert rep.uncited_sentences == ("Revenue grew 44% in 2022.",)


def test_marker_after_the_period_belongs_to_the_sentence():
    assert sentences("Revenue was $23.6 billion. [1] Margin was 45%. [2][3]") == \
        ["Revenue was $23.6 billion [1].", "Margin was 45% [2][3]."]
    assert check_citations("Revenue grew. [1] Margin was 45% in 2022.", SOURCES).uncited_sentences == \
        ("Margin was 45% in 2022.",)
    assert check_citations("Revenue was $23.6 billion. [1]", SOURCES).uncited_sentences == ()


def test_page_range_label():
    rep = check_citations("Impairment of $1.2 billion [3].", SOURCES)
    assert rep.citations[0].label == "Beta 2021 10-K, pp. 90–91"


# --- refusal and the pipeline ---------------------------------------------------------

class ListRetriever:
    def __init__(self, hits):
        self.hits, self.calls = hits, []

    def search(self, conn, query, k=10, filters=None):
        self.calls.append((query, k, filters))
        return self.hits[:k]


class ScriptedLLM:
    provider, model = "scripted", "scripted-1"

    def __init__(self, text):
        self.text, self.calls, self.last_result = text, 0, None

    def generate(self, instructions, user):
        from app.generate.llm import LLMResult
        self.calls += 1
        return LLMResult(self.text, self.model, self.provider, 100, 10, 1.0)

    def stream(self, instructions, user):
        r = self.generate(instructions, user)
        yield from (r.text[:5], r.text[5:])
        self.last_result = r


@pytest.mark.parametrize("text", [REFUSAL_TOKEN, f" {REFUSAL_TOKEN}.", f"`{REFUSAL_TOKEN}`", REFUSAL_TOKEN.lower()])
def test_refusal_token_variants(text):
    assert is_refusal(text)


def test_model_refusal_becomes_the_refusal_message():
    a = answer_question(None, "q", ListRetriever(HITS), ScriptedLLM(REFUSAL_TOKEN))
    assert a.refused and a.refusal_reason == "model" and a.text == REFUSAL_MESSAGE


def test_no_context_refuses_without_calling_the_model():
    llm = ScriptedLLM("should not be called")
    a = answer_question(None, "q", ListRetriever([]), llm)
    assert a.refused and a.refusal_reason == "no_context" and llm.calls == 0


def test_answer_carries_citations_usage_and_timings():
    r = ListRetriever(HITS)
    a = answer_question(None, "What was revenue?", r, ScriptedLLM("Revenue was $23.6 billion [1]."), k=3, budget=1000)
    assert r.calls == [("What was revenue?", 3, None)]
    assert not a.refused and [c.n for c in a.report.citations] == [1]
    assert (a.input_tokens, a.output_tokens, a.model) == (100, 10, "scripted-1")
    assert set(a.timings_ms) == {"retrieve", "generate"}
    instructions, user = a.prompt
    assert instructions == INSTRUCTIONS and user.endswith("Question: What was revenue?")


def test_stream_answer_yields_sources_deltas_then_the_answer():
    events = list(stream_answer(None, "q", ListRetriever(HITS), ScriptedLLM("Revenue grew [1]."), k=3, budget=1000))
    kinds = [e[0] for e in events]
    assert kinds[0] == "sources" and kinds[-1] == "answer" and set(kinds[1:-1]) == {"delta"}
    assert "".join(e[1] for e in events if e[0] == "delta") == "Revenue grew [1]."
    assert events[-1][1].report.citations[0].n == 1 and "first_token" in events[-1][1].timings_ms


# --- the fake model ----------------------------------------------------------------------

def test_fake_llm_quotes_the_best_matching_sentence_with_its_citation():
    user = build_user_message("What was net revenue in 2022?", pack_context(HITS, 1000))
    assert FakeLLM().generate(INSTRUCTIONS, user).text == "Net revenue was $23.6 billion in 2022, up 44%. [1]"


def test_fake_llm_refuses_off_topic_questions():
    user = build_user_message("What is the capital of France?", pack_context(HITS, 1000))
    assert FakeLLM().generate(INSTRUCTIONS, user).text == REFUSAL_TOKEN


# --- the cache ----------------------------------------------------------------------------

def test_cache_key_changes_with_anything_that_changes_the_answer():
    base = cache_key("openai", "m", "i", "u", {"max_output_tokens": 700})
    assert base == cache_key("openai", "m", "i", "u", {"max_output_tokens": 700})
    variants = [cache_key("fake", "m", "i", "u", {"max_output_tokens": 700}),
                cache_key("openai", "m2", "i", "u", {"max_output_tokens": 700}),
                cache_key("openai", "m", "i2", "u", {"max_output_tokens": 700}),
                cache_key("openai", "m", "i", "u2", {"max_output_tokens": 700}),
                cache_key("openai", "m", "i", "u", {"max_output_tokens": 701})]
    assert len({base, *variants}) == 6


def test_cached_llm_serves_repeats_from_postgres(db):
    inner = ScriptedLLM("Revenue grew [1].")
    llm = CachedLLM(inner, db)
    first = llm.generate("instr", "user")
    second = llm.generate("instr", "user")
    assert inner.calls == 1 and not first.cached and second.cached
    assert (second.text, second.input_tokens, second.output_tokens) == ("Revenue grew [1].", 100, 10)
    assert db.execute("SELECT hits FROM llm_cache").fetchone()[0] == 1


def test_cached_llm_stream_stores_then_replays(db):
    inner = ScriptedLLM("Revenue grew [1].")
    llm = CachedLLM(inner, db)
    assert "".join(llm.stream("i", "u")) == "Revenue grew [1]." and not llm.last_result.cached
    assert "".join(llm.stream("i", "u")) == "Revenue grew [1]." and llm.last_result.cached
    assert inner.calls == 1


# --- configuration ------------------------------------------------------------------------

@pytest.mark.parametrize("provider, env", [("gemini", "GEMINI_API_KEY"), ("openai", "OPENAI_API_KEY")])
def test_a_real_provider_without_its_key_fails_loudly(monkeypatch, provider, env):
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", provider)
    monkeypatch.setattr(s, "gemini_api_key", None)
    monkeypatch.setattr(s, "openai_api_key", None)
    get_llm.cache_clear()
    with pytest.raises(MissingAPIKey, match=f"{env} is empty.*LLM_PROVIDER=fake"):
        get_llm()
    monkeypatch.setattr(s, "llm_provider", "fake")
    get_llm.cache_clear()
    assert isinstance(get_llm(), FakeLLM) and get_llm("judge").model == "fake-judge"
    get_llm.cache_clear()


def test_provider_base_url_and_models_come_from_settings(monkeypatch):
    from pydantic import SecretStr
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "gemini")
    monkeypatch.setattr(s, "gemini_api_key", SecretStr("test-key-not-real"))
    monkeypatch.setattr(s, "llm_base_url", "https://example.test/v1/")
    monkeypatch.setattr(s, "llm_model", "gen-model")
    monkeypatch.setattr(s, "llm_judge_model", "judge-model")
    get_llm.cache_clear()
    gen, judge = get_llm("generate"), get_llm("judge")
    assert (gen.provider, gen.model, gen.base_url) == ("gemini", "gen-model", "https://example.test/v1/")
    assert judge.model == "judge-model" and judge.reasoning_effort == s.llm_judge_reasoning_effort
    assert str(gen.client.base_url) == "https://example.test/v1/"
    get_llm.cache_clear()


def test_settings_never_show_the_key():
    from pydantic import SecretStr
    from app.config import Settings
    s = Settings(postgres_password="p", openai_api_key=SecretStr("sk-test-not-a-real-key"),
                 gemini_api_key=SecretStr("gm-test-not-a-real-key"))
    for leaked in ("sk-test", "gm-test"):
        assert leaked not in repr(s) and leaked not in str(s.model_dump())


# --- retries ----------------------------------------------------------------------------------

def api_error(status, body=None, headers=None):
    import openai
    req = httpx.Request("POST", "https://example.test/v1/chat/completions")
    resp = httpx.Response(status, request=req, json=body or {"error": {"message": "x"}}, headers=headers or {})
    cls = {429: openai.RateLimitError, 500: openai.InternalServerError, 503: openai.InternalServerError,
           401: openai.AuthenticationError, 400: openai.BadRequestError}[status]
    return cls("error", response=resp, body=body)


def test_backoff_is_exponential_capped_jittered_and_honours_retry_after():
    assert [backoff_s(i, 1.0, 30.0, None, rng=lambda: 1.0) for i in range(7)] == [1, 2, 4, 8, 16, 30, 30]
    assert backoff_s(3, 1.0, 30.0, None, rng=lambda: 0.0) == 4.0          # jitter scales into [½, 1]
    assert backoff_s(0, 1.0, 30.0, "12", rng=lambda: 1.0) == 12.0         # Retry-After wins when longer
    assert backoff_s(0, 1.0, 30.0, "soon", rng=lambda: 1.0) == 1.0        # unparseable header ignored


def test_retries_429_and_5xx_then_succeeds():
    errors = [api_error(429), api_error(503), api_error(500, headers={"retry-after": "2"})]
    slept = []

    def call():
        if errors:
            raise errors.pop(0)
        return "ok"

    assert with_retries(call, max_retries=6, base_s=1.0, max_s=30.0, sleep=slept.append) == "ok"
    assert len(slept) == 3 and slept[2] >= 2.0


def test_does_not_retry_client_errors_or_an_empty_balance():
    quota = api_error(429, {"error": {"message": "no credits", "type": "insufficient_quota",
                                      "code": "credit_balance_exhausted"}})
    assert quota_exhausted(quota)
    for exc in (api_error(400), api_error(401), quota):
        calls = []

        def call(exc=exc):
            calls.append(1)
            raise exc
        with pytest.raises(type(exc)):
            with_retries(call, max_retries=6, base_s=1.0, max_s=30.0, sleep=lambda s: None)
        assert len(calls) == 1


def test_gives_up_after_max_retries():
    calls = []

    def call():
        calls.append(1)
        raise api_error(503)
    import openai
    with pytest.raises(openai.InternalServerError):
        with_retries(call, max_retries=3, base_s=1.0, max_s=30.0, sleep=lambda s: None)
    assert len(calls) == 4


# --- OpenAI-compatible Chat Completions client against a mocked transport ---------------------

COMPLETION = {
    "id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": "gemini-3.5-flash",
    "choices": [{"index": 0, "finish_reason": "stop",
                 "message": {"role": "assistant", "content": "Revenue was $23.6 billion [1]."}}],
    "usage": {"prompt_tokens": 812, "completion_tokens": 9, "total_tokens": 821},
}


def mock_client(handler, **kw):
    return ChatClient("gemini", "test-key-not-real", "gemini-3.5-flash",
                      "https://generativelanguage.googleapis.com/v1beta/openai/", 2048, None, kw.pop("effort", "low"),
                      10, http_client=httpx.Client(transport=httpx.MockTransport(handler)),
                      sleep=lambda s: None, **kw)


def test_chat_client_sends_chat_completions_to_the_configured_endpoint():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"], seen["body"] = str(request.url), json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json=COMPLETION)

    r = mock_client(handler).generate("instr", "user msg")
    assert seen["url"] == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert seen["body"]["model"] == "gemini-3.5-flash"
    assert seen["body"]["messages"] == [{"role": "system", "content": "instr"}, {"role": "user", "content": "user msg"}]
    assert seen["body"]["max_tokens"] == 2048 and seen["body"]["reasoning_effort"] == "low"
    assert "temperature" not in seen["body"]
    assert seen["auth"] == "Bearer test-key-not-real"
    assert (r.text, r.input_tokens, r.output_tokens, r.provider, r.truncated) == \
        ("Revenue was $23.6 billion [1].", 812, 9, "gemini", False)


def test_reasoning_effort_is_omitted_when_unset():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=COMPLETION)
    mock_client(handler, effort=None).generate("i", "u")
    assert "reasoning_effort" not in seen["body"]


def test_finish_reason_length_marks_the_answer_truncated():
    def handler(request):
        cut = {**COMPLETION, "choices": [{"index": 0, "finish_reason": "length",
                                          "message": {"role": "assistant", "content": "1"}}]}
        return httpx.Response(200, json=cut)
    assert mock_client(handler).generate("i", "u").truncated


def test_chat_client_retries_a_503_then_succeeds():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(503, json=[{"error": {"code": 503, "message": "This model is currently experiencing high demand.",
                                                        "status": "UNAVAILABLE"}}])
        return httpx.Response(200, json=COMPLETION)
    assert mock_client(handler).generate("i", "u").text.startswith("Revenue")
    assert len(calls) == 3


def test_chat_client_streams_text_deltas_with_usage():
    def handler(request: httpx.Request):
        body = json.loads(request.content)
        assert body["stream"] is True and body["stream_options"] == {"include_usage": True}
        chunks = [{"choices": [{"index": 0, "delta": {"role": "assistant", "content": d}, "finish_reason": None}]}
                  for d in ["Revenue was ", "$23.6 billion ", "[1]."]]
        chunks.append({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 812, "completion_tokens": 9, "total_tokens": 821}})
        sse = "".join(f"data: {json.dumps({'id': 'c1', 'object': 'chat.completion.chunk', 'created': 0, 'model': 'gemini-3.5-flash', **c})}\n\n"
                      for c in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse.encode())

    client = mock_client(handler)
    assert list(client.stream("instr", "user")) == ["Revenue was ", "$23.6 billion ", "[1]."]
    r = client.last_result
    assert (r.text, r.input_tokens, r.output_tokens, r.finish_reason) == ("Revenue was $23.6 billion [1].", 812, 9, "stop")


def test_auth_errors_are_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(401, json={"error": {"message": "API key not valid", "type": "invalid_request_error"}})

    import openai
    with pytest.raises(openai.AuthenticationError):
        mock_client(handler).generate("i", "u")
    assert len(calls) == 1


def test_cache_keeps_the_truncation_flag(db):
    from app.generate.llm import LLMResult

    class Cut(ScriptedLLM):
        def generate(self, instructions, user):
            self.calls += 1
            return LLMResult("1", self.model, self.provider, 10, 60, 1.0, finish_reason="length")
    inner = Cut("unused")
    llm = CachedLLM(inner, db)
    assert llm.generate("i", "u").truncated and llm.generate("i", "u").truncated and inner.calls == 1
