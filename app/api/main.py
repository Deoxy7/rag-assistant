"""FastAPI app: /health, /documents, /query (JSON) and /query/stream (SSE).

    uvicorn app.api.main:app --port 8000        (or: make serve)

Endpoints are plain `def` (not `async def`): retrieval, reranking and the
OpenAI SDK are blocking calls, and FastAPI runs sync endpoints and sync
generators in its thread pool, so they don't block the event loop (card #32).
"""

import hashlib
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager

import openai
import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.sse import EventSourceResponse, format_sse_event

from app.api.schemas import (CitationOut, DocumentOut, ErrorOut, Health, QueryRequest, QueryResponse, SourceOut,
                             QuarantinedOut, Stats, Usage)
from app.config import get_settings
from app.embed.embedder import get_embedder, model_key
from app.generate.answer import Answer, answer_question, stream_answer
from app.generate.llm import CachedLLM, MissingAPIKey, get_llm, quota_exhausted, server_retry_delay_s
from app.generate.prompt import REFUSAL_TOKEN, PackedContext
from app.retrieve.rerank import get_reranker, retriever_from_settings
from app.retrieve.types import Filters
from app.store import repository as repo
from app.store.db import connect
from app.telemetry import logs

log = logging.getLogger("rag.api")
reqlog = logging.getLogger("rag.request")


class State:
    """Process-wide objects built once at startup (models are slow to load)."""

    chunk_set_id: int | None = None   # set at startup
    retriever = None


state = State()


def resolve_chunk_set(conn) -> int:
    s = get_settings()
    cs = repo.find_chunk_set(conn, s.chunk_strategy, s.chunk_size, s.chunk_overlap,
                             model_key(s.embedding_model, s.embedding_model_revision))
    if cs is None:
        raise RuntimeError(f"no chunk set for {s.chunk_strategy}/{s.chunk_size}/{s.chunk_overlap}: run `make ingest`")
    return cs


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    logs.configure(s.log_format, s.log_level)
    with connect() as conn:
        state.chunk_set_id = resolve_chunk_set(conn)
    t0 = time.perf_counter()
    embedder = get_embedder()
    embedder.embed_query("warm up")                 # first MPS call compiles kernels
    if s.rerank_enabled:
        get_reranker().score("warm up", ["warm up"])
    state.retriever = retriever_from_settings(state.chunk_set_id, embedder=embedder)
    log.info("models ready in %.1f s (chunk set %d)", time.perf_counter() - t0, state.chunk_set_id)
    yield


app = FastAPI(title="10-K RAG assistant", version="0.10.0", lifespan=lifespan,
              description="Answers questions about ten SEC 10-K filings with page-level citations.")


# --- request id + errors ------------------------------------------------------------------

@app.middleware("http")
async def request_id(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    request.state.request_id = rid
    request.state.error_code = None
    request.state.logged = False
    t0 = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - t0) * 1000
    response.headers["x-request-id"] = rid
    # One structured line per request. For a stream this is the time to the response
    # headers; the stream logs its own completion (event "answer") when it ends.
    reqlog.info("http", extra={"fields": {"request_id": rid, "method": request.method, "path": request.url.path,
                                          "status": response.status_code, "ms": round(ms, 1),
                                          "error": request.state.error_code}})
    if request.url.path in ("/query", "/query/stream") and not request.state.logged:
        # Failed before an answer existed (validation, configuration, provider error): still one row.
        record(rid, request.url.path, response.status_code, request.state.error_code, None, None, ms)
    return response


def error(request: Request, status: int, code: str, message: str) -> JSONResponse:
    request.state.error_code = code
    body = ErrorOut(request_id=request.state.request_id, error=code, message=message)
    return JSONResponse(status_code=status, content=body.model_dump())


def record(rid: str, endpoint: str, status: int, error_code: str | None, question: str | None,
           a: Answer | None, total_ms: float) -> None:
    """Write one request_log row and one structured log line. Best effort: telemetry must never fail a request."""
    row = {"request_id": rid, "endpoint": endpoint, "status": status, "error": error_code, "total_ms": round(total_ms, 2)}
    if question is not None:
        row.update(question_sha256=hashlib.sha256(question.encode()).hexdigest(), question_chars=len(question))
    if a is not None:
        row.update(provider=a.provider, model=a.model, input_tokens=a.input_tokens, output_tokens=a.output_tokens,
                   cached=a.cached, refused=a.refused, truncated=a.truncated, list_usd=a.list_usd,
                   billed_usd=a.billed_usd, timings_ms={k: round(v, 2) for k, v in a.timings_ms.items()},
                   counters=a.counters)
        reqlog.info("answer", extra={"fields": {k: v for k, v in row.items() if k != "question_sha256"}})
    if not get_settings().request_log_enabled:
        return
    try:
        with connect() as conn:
            repo.log_request(conn, row)
    except Exception:  # noqa: BLE001
        log.warning("request_log write failed for %s", rid, exc_info=True)


def classify(exc: Exception) -> tuple[int, str, str]:
    """Map a failure to (HTTP status, error code, safe message). Never echoes secrets or SQL."""
    if isinstance(exc, MissingAPIKey):
        return 503, "llm_not_configured", str(exc)
    if isinstance(exc, openai.AuthenticationError):
        return 502, "llm_auth_failed", "The LLM provider rejected the API key."
    if isinstance(exc, openai.RateLimitError):
        # Both arrive as HTTP 429; only the first gets better by waiting.
        if quota_exhausted(exc):
            wait = server_retry_delay_s(exc)
            when = f" It resets in about {wait / 3600:.1f} h." if wait else ""
            return 503, "llm_quota_exhausted", ("The LLM provider's quota is used up (no credits, or the daily "
                                                f"free-tier limit).{when} Add billing or wait, then retry.")
        return 503, "llm_rate_limited", "The LLM provider is rate-limiting requests; retry later."
    if isinstance(exc, openai.APITimeoutError):
        return 504, "llm_timeout", "The LLM provider did not respond in time."
    if isinstance(exc, openai.APIStatusError) and quota_exhausted(exc):     # e.g. 402 credits depleted
        return 503, "llm_quota_exhausted", ("The LLM provider's credits or quota are used up. "
                                            "Add credits or wait for the quota to reset, then retry.")
    if isinstance(exc, (openai.APIConnectionError, openai.APIStatusError)):
        return 502, "llm_unavailable", "The LLM provider returned an error."
    if isinstance(exc, psycopg.OperationalError):
        return 503, "database_unavailable", "The database is not reachable."
    return 500, "internal_error", "Unexpected error; see server logs with this request id."


@app.exception_handler(RequestValidationError)
async def validation_failed(request: Request, exc: RequestValidationError):
    first = exc.errors()[0]
    where = ".".join(str(x) for x in first["loc"] if x != "body")
    return error(request, 422, "invalid_request", f"{where}: {first['msg']}")


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    code, message = exc.detail if isinstance(exc.detail, tuple) else ("http_error", str(exc.detail))
    return error(request, exc.status_code, code, message)


async def expected_failure(request: Request, exc: Exception):
    status, code, message = classify(exc)
    log.warning("request %s: %s (%s)", request.state.request_id, code, type(exc).__name__)
    return error(request, status, code, message)


# Known failure types get their own handlers: Starlette runs these inside the app
# and the error is fully handled. The catch-all `Exception` handler below runs in
# the outermost middleware, which re-raises after responding (logged as a crash),
# which is right only for genuinely unexpected errors.
for _exc in (MissingAPIKey, openai.APIError, psycopg.OperationalError):
    app.add_exception_handler(_exc, expected_failure)


@app.exception_handler(Exception)
async def unexpected(request: Request, exc: Exception):
    status, code, message = classify(exc)
    if status == 500:
        log.exception("request %s failed", request.state.request_id)
    return error(request, status, code, message)


# --- dependencies ---------------------------------------------------------------------------

def db():
    with connect() as conn:
        yield conn


def llm_client():
    """The configured LLM, wrapped in the response cache. Raises MissingAPIKey (→ 503) if unconfigured."""
    llm = get_llm()
    return CachedLLM(llm, connect) if get_settings().llm_cache_enabled else llm


def to_filters(conn, req: QueryRequest) -> Filters:
    if req.companies:
        unknown = sorted(set(req.companies) - repo.known_companies(conn))
        if unknown:
            raise HTTPException(422, ("unknown_company", f"unknown companies {unknown}; see GET /documents"))
    return Filters(tuple(req.companies) if req.companies else None,
                   tuple(req.fiscal_years) if req.fiscal_years else None)


# --- serialisation --------------------------------------------------------------------------

def sources_out(ctx: PackedContext) -> list[SourceOut]:
    return [SourceOut(n=s.n, chunk_id=s.hit.chunk_id, doc_key=s.hit.doc_key, company=s.hit.company,
                      fiscal_year=s.hit.fiscal_year, page_number=s.hit.page_number, page_end=s.hit.page_end,
                      section=list(s.hit.section), score=s.hit.score, text=s.hit.text) for s in ctx.sources]


def response_out(rid: str, a: Answer) -> QueryResponse:
    cites = [CitationOut(n=c.n, label=c.label, chunk_id=c.chunk_id, doc_key=c.doc_key, page_number=c.page_number,
                         page_end=c.page_end, char_start=c.char_start, char_end=c.char_end)
             for c in (a.report.citations if a.report else ())]
    return QueryResponse(
        request_id=rid, answer=a.text, refused=a.refused, refusal_reason=a.refusal_reason, citations=cites,
        sources=sources_out(a.context),
        invalid_markers=list(a.report.invalid_markers) if a.report else [],
        uncited_sentences=list(a.report.uncited_sentences) if a.report else [],
        usage=Usage(provider=a.provider, model=a.model, input_tokens=a.input_tokens, output_tokens=a.output_tokens,
                    cached=a.cached, truncated=a.truncated, list_usd=a.list_usd, billed_usd=a.billed_usd),
        timings_ms={k: round(v, 1) for k, v in a.timings_ms.items()}, counters=a.counters,
        quarantined=quarantined_out(a.context))


def quarantined_out(ctx: PackedContext) -> list[QuarantinedOut]:
    return [QuarantinedOut(chunk_id=h.chunk_id, doc_key=h.doc_key, page_number=h.page_number, signals=list(sig))
            for h, sig in ctx.quarantined]


# --- endpoints ------------------------------------------------------------------------------

@app.get("/health", response_model=Health)
def health():
    s = get_settings()
    try:
        with connect() as conn:
            conn.execute("SELECT 1")
        database = True
    except psycopg.OperationalError:
        database = False
    try:
        active_model, llm_ready, detail = get_llm().model, True, None
    except (MissingAPIKey, ValueError) as e:
        active_model, llm_ready, detail = s.llm_model, False, str(e)
    body = Health(status="ok" if database and llm_ready else "degraded", database=database,
                  chunk_set_id=state.chunk_set_id, retrieval_mode=s.retrieval_mode, rerank_enabled=s.rerank_enabled,
                  llm_provider=s.llm_provider, llm_model=active_model, llm_ready=llm_ready, detail=detail)
    return JSONResponse(status_code=200 if database else 503, content=body.model_dump())


@app.get("/documents", response_model=list[DocumentOut])
def documents(conn=Depends(db)):
    return [DocumentOut(**d) for d in repo.list_documents(conn, state.chunk_set_id)]


@app.post("/query", response_model=QueryResponse, responses={422: {"model": ErrorOut}, 503: {"model": ErrorOut}})
def query(req: QueryRequest, request: Request, conn=Depends(db), llm=Depends(llm_client)):
    t0 = time.perf_counter()
    filters = to_filters(conn, req)
    a = answer_question(conn, req.question, state.retriever, llm, filters=filters, k=req.k)
    record(request.state.request_id, "/query", 200, None, req.question, a, (time.perf_counter() - t0) * 1000)
    request.state.logged = True
    return response_out(request.state.request_id, a)


@app.get("/stats", response_model=Stats)
def stats(hours: float = 24.0, conn=Depends(db)):
    """Aggregates from request_log over the last `hours` (default 24): volume, errors by code, cache and
    refusal rates, tokens, cost (list and billed), and p50/p95 latency per stage."""
    if not 0 < hours <= 24 * 90:
        raise HTTPException(422, ("invalid_request", "hours must be in (0, 2160]"))
    return Stats(**repo.request_stats(conn, hours))


class RefusalGate:
    """Hold streamed text while it could still be the start of REFUSAL_TOKEN.

    The model is told to reply with exactly INSUFFICIENT_CONTEXT when it can't
    answer. Streaming that raw token to a user would look like a bug, so text is
    held back until it can no longer be a prefix of the token; a refusal is then
    reported once, cleanly, in the final `answer` event.
    """

    def __init__(self):
        self.held = ""
        self.open = False

    def feed(self, delta: str) -> str:
        if self.open:
            return delta
        self.held += delta
        probe = self.held.strip().strip("`'\"").upper()
        if REFUSAL_TOKEN.startswith(probe) or probe.rstrip(".") == REFUSAL_TOKEN:
            return ""                                   # still possibly a refusal: keep holding
        self.open, out, self.held = True, self.held, ""
        return out


@app.post("/query/stream", response_class=StreamingResponse,
          responses={200: {"description": "SSE stream: `sources`, `delta`…, then `answer` (or `error`)",
                           "content": {"text/event-stream": {}}},
                     422: {"model": ErrorOut}, 503: {"model": ErrorOut}})
def query_stream(req: QueryRequest, request: Request, llm=Depends(llm_client)):
    """Server-Sent Events. Validation and configuration errors are returned as normal JSON errors *before*
    the stream starts (MissingAPIKey → 503 from the dependency); failures during generation arrive as an
    `error` event, because the 200 status line has already been sent."""
    rid = request.state.request_id
    request.state.logged = True      # the stream records its own row when it finishes (or fails)
    t_start = time.perf_counter()
    conn = connect()
    try:
        filters = to_filters(conn, req)
    except Exception:
        conn.close()
        raise

    def sse(event: str, data, id: str | None = None) -> bytes:
        # JSON for every payload (a delta is a JSON string), so newlines inside text are escaped.
        return format_sse_event(event=event, id=id, data_str=json.dumps(data, ensure_ascii=False))

    def events():
        gate = RefusalGate()
        try:
            for kind, payload in stream_answer(conn, req.question, state.retriever, llm, filters=filters, k=req.k):
                if kind == "sources":
                    conn.close()                        # retrieval done: release the DB before the LLM streams
                    yield sse("sources", [s.model_dump() for s in sources_out(payload)], id=rid)
                elif kind == "delta":
                    text = gate.feed(payload)
                    if text:
                        yield sse("delta", text)
                else:
                    record(rid, "/query/stream", 200, None, req.question, payload, (time.perf_counter() - t_start) * 1000)
                    yield sse("answer", response_out(rid, payload).model_dump())
        except Exception as exc:                        # after the 200 header: report in-band
            status, code, message = classify(exc)
            if status == 500:
                log.exception("stream %s failed", rid)
            record(rid, "/query/stream", status, code, req.question, None, (time.perf_counter() - t_start) * 1000)
            yield sse("error", {"request_id": rid, "error": code, "message": message, "status": status})
        finally:
            if not conn.closed:
                conn.close()

    # Returned as a ready response (not a `yield` endpoint) so that validation, filter and
    # configuration errors above become normal JSON errors before any event is sent.
    # no-cache + X-Accel-Buffering: proxies (e.g. nginx) must not buffer the stream.
    return EventSourceResponse(events(), headers={"cache-control": "no-cache", "x-accel-buffering": "no"})


def openapi_json() -> str:
    return json.dumps(app.openapi(), indent=2)
