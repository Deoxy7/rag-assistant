"""LLM clients behind one small interface, plus a response cache.

    client.generate(instructions, user) -> LLMResult
    client.stream(instructions, user)   -> iterator of text deltas, then .last_result

ChatClient speaks the OpenAI Chat Completions protocol to any compatible
endpoint: Gemini's (https://generativelanguage.googleapis.com/v1beta/openai/,
the default), OpenAI's, or a local server. Provider, base URL, model and key
are all settings, so switching provider is an edit to .env (card x-llm-provider).
Chat Completions rather than OpenAI's newer Responses API because the Gemini
endpoint doesn't serve Responses (404, measured; T-045).

FakeLLM is a deterministic, offline stand-in used by tests and by development
without an API key: it answers by quoting the source sentence that shares the
most words with the question, so the whole pipeline (packing → generation →
citation check) runs end to end. Its answers are *not* model quality; numbers
measured with it are labelled so.
"""

import hashlib
import json
import logging
import random
import re
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache

import psycopg

from app.config import get_settings
from app.generate.prompt import PROMPT_VERSION, REFUSAL_TOKEN, count_llm_tokens
from app.store import repository as repo

log = logging.getLogger("rag.llm")


@dataclass(frozen=True)
class LLMResult:
    text: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cached: bool = False
    finish_reason: str | None = None   # "stop" | "length" (hit max tokens) | … ; None when unknown

    @property
    def truncated(self) -> bool:
        return self.finish_reason == "length"


class MissingAPIKey(RuntimeError):
    pass


# --- retries ---------------------------------------------------------------------------

def _error_dict(exc: Exception) -> dict:
    """The provider's error object: OpenAI sends {"error": {...}}, Gemini's compat endpoint [{"error": {...}}]."""
    body = getattr(exc, "body", None) or {}
    if isinstance(body, list):
        body = body[0] if body and isinstance(body[0], dict) else {}
    err = body.get("error", body) if isinstance(body, dict) else {}
    return err if isinstance(err, dict) else {}


def server_retry_delay_s(exc: Exception) -> float | None:
    """How long the provider says to wait: Retry-After header, Gemini's RetryInfo ("20949s"), or its
    message ("Please retry in 5h49m5.47s"). None if it didn't say."""
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    try:
        if headers.get("retry-after"):
            return float(headers["retry-after"])
    except ValueError:
        pass
    err = _error_dict(exc)
    for d in err.get("details") or []:
        if isinstance(d, dict) and str(d.get("@type", "")).endswith("RetryInfo"):
            m = re.fullmatch(r"([\d.]+)s", str(d.get("retryDelay", "")))
            if m:
                return float(m.group(1))
    # Gemini: "Please retry in 5h49m5.4s"; Groq: "Please try again in 7m12.5s".
    m = re.search(r"(?:retry|try again) in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", str(err.get("message", "")))
    if m and any(m.groups()):
        h, mi, s = (float(x) if x else 0.0 for x in m.groups())
        return h * 3600 + mi * 60 + s
    return None


def quota_exhausted(exc: Exception) -> bool:
    """An error that waiting won't fix within a run: HTTP 402 (no prepaid credits), an empty balance (OpenAI: insufficient_quota /
    credit_balance_exhausted, T-038) or a *daily* quota (Gemini free tier: 20 requests/day per model,
    quotaId GenerateRequestsPerDay…, T-052). Per-minute limits are not this: they clear in seconds."""
    if getattr(exc, "status_code", None) == 402:   # Payment Required: e.g. Gemini "prepayment credits are depleted" (T-054)
        return True
    err = _error_dict(exc)
    codes = {getattr(exc, "code", None), err.get("code"), err.get("type")}
    if codes & {"insufficient_quota", "credit_balance_exhausted"}:
        return True
    for d in err.get("details") or []:
        for v in (d.get("violations") or []) if isinstance(d, dict) else []:
            if "PerDay" in str(v.get("quotaId", "")):
                return True
    # Groq: "Rate limit reached for model … on tokens per day (TPD): Limit 200000, Used …"
    return bool(re.search(r"per day|\(TPD\)|\(RPD\)", str(err.get("message", "")), re.I))


def retryable(exc: Exception) -> bool:
    """429 (rate limit, not an exhausted quota), any 5xx (e.g. Gemini's 503 'high demand'), timeouts, connection drops."""
    import openai
    if isinstance(exc, openai.RateLimitError):
        return not quota_exhausted(exc)
    if isinstance(exc, (openai.APITimeoutError, openai.APIConnectionError)):
        return True
    return isinstance(exc, openai.APIStatusError) and exc.status_code >= 500


def backoff_s(attempt: int, base_s: float, max_s: float, retry_after: str | None, rng=random.random) -> float:
    """Exponential backoff with jitter: base · 2^attempt, capped, scaled into [½, 1] at random so that
    many clients retrying together don't re-collide; a server's Retry-After (seconds) wins if longer."""
    delay = min(max_s, base_s * 2 ** attempt) * (0.5 + 0.5 * rng())
    try:
        return max(delay, min(max_s, float(retry_after))) if retry_after else delay
    except ValueError:
        return delay


def with_retries(call: Callable, max_retries: int, base_s: float, max_s: float, sleep=time.sleep):
    """Run `call()`; on a retryable error wait and try again, up to max_retries extra attempts."""
    for attempt in range(max_retries + 1):
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 — filtered by retryable()
            if attempt == max_retries or not retryable(exc):
                raise
            asked = server_retry_delay_s(exc)
            if asked is not None and asked > max_s:
                raise      # the provider wants longer than we'd ever wait inside one call: fail now
            wait = backoff_s(attempt, base_s, max_s, str(asked) if asked is not None else None)
            log.warning("LLM call failed (%s %s); retry %d/%d in %.1f s", type(exc).__name__,
                        getattr(exc, "status_code", ""), attempt + 1, max_retries, wait)
            sleep(wait)


class ChatClient:
    """OpenAI-compatible Chat Completions client (Gemini, OpenAI, …)."""

    def __init__(self, provider: str, api_key: str, model: str, base_url: str | None, max_output_tokens: int,
                 temperature: float | None, reasoning_effort: str | None, timeout_s: float,
                 max_retries: int = 6, retry_base_s: float = 1.0, retry_max_s: float = 30.0,
                 http_client=None, sleep=time.sleep):
        from openai import OpenAI   # imported here so the fake path never needs the SDK configured

        self.provider, self.model, self.base_url = provider, model, base_url
        self.max_output_tokens, self.temperature, self.reasoning_effort = max_output_tokens, temperature, reasoning_effort
        self.retry = dict(max_retries=max_retries, base_s=retry_base_s, max_s=retry_max_s, sleep=sleep)
        # max_retries=0: the SDK's own retries are off, so retries happen exactly once, here, with our policy.
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_s, max_retries=0,
                             http_client=http_client)
        self.last_result: LLMResult | None = None

    def params(self) -> dict:
        """Request parameters; also part of the cache key."""
        # max_tokens covers *thinking* tokens too on Gemini 3.x Flash: with 60 the answer was cut
        # to "1" (finish_reason "length"; T-046). Hence a generous default and the truncated flag.
        p = {"max_tokens": self.max_output_tokens}
        if self.temperature is not None:
            p["temperature"] = self.temperature
        if self.reasoning_effort is not None:
            p["reasoning_effort"] = self.reasoning_effort
        return p

    def _messages(self, instructions: str, user: str) -> list[dict]:
        return [{"role": "system", "content": instructions}, {"role": "user", "content": user}]

    def generate(self, instructions: str, user: str) -> LLMResult:
        t0 = time.perf_counter()
        r = with_retries(lambda: self.client.chat.completions.create(
            model=self.model, messages=self._messages(instructions, user), **self.params()), **self.retry)
        u, choice = r.usage, r.choices[0]
        return LLMResult(choice.message.content or "", r.model or self.model, self.provider,
                         u.prompt_tokens if u else 0, u.completion_tokens if u else 0,
                         (time.perf_counter() - t0) * 1000, finish_reason=choice.finish_reason)

    def stream(self, instructions: str, user: str) -> Iterator[str]:
        """Streams text deltas. Retries apply to opening the stream only: once text has been
        yielded to the caller it can't be taken back, so a mid-stream failure propagates."""
        t0 = time.perf_counter()
        events = with_retries(lambda: self.client.chat.completions.create(
            model=self.model, messages=self._messages(instructions, user), stream=True,
            stream_options={"include_usage": True}, **self.params()), **self.retry)
        parts, usage, finish, model = [], None, None, self.model
        for chunk in events:
            model = chunk.model or model
            if chunk.usage:
                usage = chunk.usage
            for c in chunk.choices:
                if c.delta and c.delta.content:
                    parts.append(c.delta.content)
                    yield c.delta.content
                if c.finish_reason:
                    finish = c.finish_reason
        self.last_result = LLMResult("".join(parts), model, self.provider, usage.prompt_tokens if usage else 0,
                                     usage.completion_tokens if usage else 0, (time.perf_counter() - t0) * 1000,
                                     finish_reason=finish)


WORD = re.compile(r"[a-z0-9]+")
STOP = set("a an the of in on for to and or is was were be by with as at from that this what which how did does do "
           "has have had its it are fy fiscal year company".split())


class FakeLLM:
    """Extractive stand-in: cite the source sentence with the most question words.

    Refuses (REFUSAL_TOKEN) when no source sentence shares at least two content
    words with the question, the same contract the real model is given.
    """

    provider = "fake"

    def __init__(self, model: str = "fake-extractive-1"):
        self.model = model
        self.last_result: LLMResult | None = None

    def _answer(self, user: str) -> str:
        sources_part, _, question = user.rpartition("\nQuestion: ")
        q = {w for w in WORD.findall(question.lower()) if w not in STOP}
        best, best_n, best_overlap = None, None, 1
        for block in re.split(r"\n(?=\[\d+\] )", sources_part):
            m = re.match(r"\[(\d+)\] [^\n]*\n(.*)", block, re.S)
            if not m:
                continue
            for sent in re.split(r"(?<=[.!?])\s+|\n+", m.group(2)):
                overlap = len(q & set(WORD.findall(sent.lower())))
                if overlap > best_overlap:
                    best, best_n, best_overlap = sent.strip(), int(m.group(1)), overlap
        if best is None:
            return REFUSAL_TOKEN
        return f"{best.rstrip('.')}. [{best_n}]"

    def generate(self, instructions: str, user: str) -> LLMResult:
        t0 = time.perf_counter()
        text = self._answer(user)
        return LLMResult(text, self.model, self.provider, count_llm_tokens(instructions) + count_llm_tokens(user),
                         count_llm_tokens(text), (time.perf_counter() - t0) * 1000)

    def stream(self, instructions: str, user: str) -> Iterator[str]:
        result = self.generate(instructions, user)
        for piece in re.findall(r"\S+\s*", result.text):
            yield piece
        self.last_result = result


def cache_key(provider: str, model: str, instructions: str, user: str, params: dict, base_url: str | None = None) -> str:
    """sha256 over everything that determines the response: prompt version, provider, endpoint, model,
    instructions, the full user message (question + packed sources, so retrieval config is in it) and params."""
    payload = json.dumps({"v": PROMPT_VERSION, "provider": provider, "base_url": base_url, "model": model,
                          "instructions": instructions, "input": user, "params": params},
                         sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CachedLLM:
    """Wraps a client: identical requests are answered from Postgres, not the API.

    `db` is either an open connection (scripts, tests) or a zero-argument function
    returning a new connection (the API). With a function, each cache read and
    write uses its own short-lived connection, so a request streaming from the
    LLM for several seconds doesn't hold a database connection the whole time.
    """

    def __init__(self, inner, db):
        self.inner, self.db = inner, db
        self.provider, self.model = inner.provider, inner.model
        self.last_result: LLMResult | None = None

    @contextmanager
    def _conn(self):
        if isinstance(self.db, psycopg.Connection):
            yield self.db
            return
        with self.db() as conn:   # psycopg: commits on clean exit, closes the connection
            yield conn

    def _key(self, instructions: str, user: str) -> str:
        params = self.inner.params() if hasattr(self.inner, "params") else {}
        return cache_key(self.inner.provider, self.inner.model, instructions, user, params,
                         getattr(self.inner, "base_url", None))

    def generate(self, instructions: str, user: str) -> LLMResult:
        key = self._key(instructions, user)
        t0 = time.perf_counter()
        with self._conn() as conn:
            hit = repo.llm_cache_get(conn, key)
        if hit:
            return LLMResult(hit[0], self.inner.model, self.inner.provider, hit[1], hit[2],
                             (time.perf_counter() - t0) * 1000, cached=True, finish_reason=hit[3])
        r = self.inner.generate(instructions, user)
        with self._conn() as conn:
            repo.llm_cache_put(conn, key, r.provider, r.model, r.text, r.input_tokens, r.output_tokens, r.finish_reason)
        return r

    def stream(self, instructions: str, user: str) -> Iterator[str]:
        key = self._key(instructions, user)
        t0 = time.perf_counter()
        with self._conn() as conn:
            hit = repo.llm_cache_get(conn, key)
        if hit:
            self.last_result = LLMResult(hit[0], self.inner.model, self.inner.provider, hit[1], hit[2],
                                         (time.perf_counter() - t0) * 1000, cached=True, finish_reason=hit[3])
            yield hit[0]
            return
        yield from self.inner.stream(instructions, user)
        r = self.inner.last_result
        with self._conn() as conn:
            repo.llm_cache_put(conn, key, r.provider, r.model, r.text, r.input_tokens, r.output_tokens, r.finish_reason)
        self.last_result = r


KEY_SETTING = {"gemini": ("gemini_api_key", "GEMINI_API_KEY"), "openai": ("openai_api_key", "OPENAI_API_KEY"),
               "groq": ("groq_api_key", "GROQ_API_KEY")}


@lru_cache(maxsize=4)
def get_llm(role: str = "generate"):
    """The configured client for a role; not cache-wrapped (CachedLLM needs a DB).

    "generate" uses LLM_PROVIDER / LLM_BASE_URL / LLM_MODEL; "judge" uses its own
    LLM_JUDGE_PROVIDER / LLM_JUDGE_BASE_URL / LLM_JUDGE_MODEL, so the judge can be a
    different model family on a different provider.
    """
    s = get_settings()
    if role not in ("generate", "judge"):
        raise ValueError(f"unknown LLM role {role!r}")
    judge = role == "judge"
    provider = s.llm_judge_provider if judge else s.llm_provider
    if provider == "fake" or s.llm_provider == "fake":
        # Offline mode is global: LLM_PROVIDER=fake never lets the judge call a real API.
        return FakeLLM(model="fake-judge" if judge else "fake-extractive-1")
    if provider not in KEY_SETTING:
        raise ValueError(f"{'LLM_JUDGE_PROVIDER' if judge else 'LLM_PROVIDER'} must be one of "
                         f"{sorted(KEY_SETTING) + ['fake']}, not {provider!r}")
    attr, env = KEY_SETTING[provider]
    secret = getattr(s, attr)
    key = secret.get_secret_value().strip() if secret else ""
    if not key:
        var = "LLM_JUDGE_PROVIDER" if judge else "LLM_PROVIDER"
        raise MissingAPIKey(f"{var}={provider} but {env} is empty. Add it to .env, "
                            "or set LLM_PROVIDER=fake to run offline with the deterministic fake model.")
    return ChatClient(provider, key, s.llm_judge_model if judge else s.llm_model,
                      s.llm_judge_base_url if judge else s.llm_base_url,
                      s.llm_judge_max_output_tokens if judge else s.llm_max_output_tokens, s.llm_temperature,
                      s.llm_judge_reasoning_effort if judge else s.llm_reasoning_effort, s.llm_timeout_s,
                      s.llm_max_retries, s.llm_retry_base_s, s.llm_retry_max_s)
