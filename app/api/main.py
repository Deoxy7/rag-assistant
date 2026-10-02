"""FastAPI app: /health, /documents, /query (JSON) and /query/stream (SSE).

    uvicorn app.api.main:app --port 8000        (or: make serve)

Endpoints are plain `def` (not `async def`): retrieval, reranking and the
OpenAI SDK are blocking calls, and FastAPI runs sync endpoints and sync
generators in its thread pool, so they don't block the event loop (card #32).
"""

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
                             Usage)
from app.config import get_settings
from app.embed.embedder import get_embedder, model_key
from app.generate.answer import Answer, answer_question, stream_answer
from app.generate.llm import CachedLLM, MissingAPIKey, get_llm
from app.generate.prompt import REFUSAL_TOKEN, PackedContext
from app.retrieve.rerank import get_reranker, retriever_from_settings
from app.retrieve.types import Filters
from app.store import repository as repo
from app.store.db import connect

log = logging.getLogger("rag.api")


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
    response = await call_next(request)
    response.headers["x-request-id"] = rid
    return response


def error(request: Request, status: int, code: str, message: str) -> JSONResponse:
    body = ErrorOut(request_id=request.state.request_id, error=code, message=message)
    return JSONResponse(status_code=status, content=body.model_dump())


def quota_exhausted(exc: Exception) -> bool:
    """OpenAI reports an empty balance as a 429 with code insufficient_quota / credit_balance_exhausted."""
    body = getattr(exc, "body", None) or {}
    err = body.get("error", body) if isinstance(body, dict) else {}
    codes = {getattr(exc, "code", None), err.get("code") if isinstance(err, dict) else None,
             err.get("type") if isinstance(err, dict) else None}
    return bool(codes & {"insufficient_quota", "credit_balance_exhausted"})


def classify(exc: Exception) -> tuple[int, str, str]:
    """Map a failure to (HTTP status, error code, safe message). Never echoes secrets or SQL."""
    if isinstance(exc, MissingAPIKey):
        return 503, "llm_not_configured", str(exc)
    if isinstance(exc, openai.AuthenticationError):
        return 502, "llm_auth_failed", "The LLM provider rejected the API key."
    if isinstance(exc, openai.RateLimitError):
        # Both arrive as HTTP 429; only the first gets better by waiting.
        if quota_exhausted(exc):
            return 503, "llm_quota_exhausted", "The LLM account has no credits left; add credits, then retry."
        return 503, "llm_rate_limited", "The LLM provider is rate-limiting requests; retry later."
    if isinstance(exc, openai.APITimeoutError):
        return 504, "llm_timeout", "The LLM provider did not respond in time."
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
                    cached=a.cached),
        timings_ms={k: round(v, 1) for k, v in a.timings_ms.items()})


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
    filters = to_filters(conn, req)
    a = answer_question(conn, req.question, state.retriever, llm, filters=filters, k=req.k)
    return response_out(request.state.request_id, a)


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
                    yield sse("answer", response_out(rid, payload).model_dump())
        except Exception as exc:                        # after the 200 header: report in-band
            status, code, message = classify(exc)
            if status == 500:
                log.exception("stream %s failed", rid)
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
