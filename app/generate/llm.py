"""LLM clients behind one small interface, plus a response cache.

    client.generate(instructions, user) -> LLMResult
    client.stream(instructions, user)   -> iterator of text deltas, then .last_result

OpenAIClient calls the Responses API. FakeLLM is a deterministic, offline
stand-in used by tests and by development without an API key: it answers by
quoting the source sentence that shares the most words with the question, so
the whole pipeline (packing → generation → citation check) runs end to end.
Its answers are *not* model quality; numbers measured with it are labelled so.
"""

import hashlib
import json
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache

import psycopg

from app.config import get_settings
from app.generate.prompt import PROMPT_VERSION, REFUSAL_TOKEN, count_llm_tokens
from app.store import repository as repo


@dataclass(frozen=True)
class LLMResult:
    text: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cached: bool = False


class MissingAPIKey(RuntimeError):
    pass


class OpenAIClient:
    provider = "openai"

    def __init__(self, api_key: str, model: str, max_output_tokens: int, temperature: float | None,
                 timeout_s: float, http_client=None):
        from openai import OpenAI   # imported here so the fake path never needs the SDK configured

        self.model, self.max_output_tokens, self.temperature = model, max_output_tokens, temperature
        self.client = OpenAI(api_key=api_key, timeout=timeout_s, max_retries=2, http_client=http_client)
        self.last_result: LLMResult | None = None

    def params(self) -> dict:
        p = {"max_output_tokens": self.max_output_tokens}
        if self.temperature is not None:
            p["temperature"] = self.temperature
        return p

    def generate(self, instructions: str, user: str) -> LLMResult:
        t0 = time.perf_counter()
        r = self.client.responses.create(model=self.model, instructions=instructions, input=user,
                                         store=False, **self.params())
        u = r.usage
        return LLMResult(r.output_text, r.model, self.provider, u.input_tokens if u else 0,
                         u.output_tokens if u else 0, (time.perf_counter() - t0) * 1000)

    def stream(self, instructions: str, user: str) -> Iterator[str]:
        t0 = time.perf_counter()
        parts, final = [], None
        with self.client.responses.stream(model=self.model, instructions=instructions, input=user,
                                          store=False, **self.params()) as events:
            for event in events:
                if event.type == "response.output_text.delta":
                    parts.append(event.delta)
                    yield event.delta
            final = events.get_final_response()
        u = final.usage
        self.last_result = LLMResult("".join(parts), final.model, self.provider, u.input_tokens if u else 0,
                                     u.output_tokens if u else 0, (time.perf_counter() - t0) * 1000)


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


def cache_key(provider: str, model: str, instructions: str, user: str, params: dict) -> str:
    """sha256 over everything that determines the response (and the prompt version)."""
    payload = json.dumps({"v": PROMPT_VERSION, "provider": provider, "model": model, "instructions": instructions,
                          "input": user, "params": params}, sort_keys=True, ensure_ascii=False)
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
        return cache_key(self.inner.provider, self.inner.model, instructions, user, params)

    def generate(self, instructions: str, user: str) -> LLMResult:
        key = self._key(instructions, user)
        t0 = time.perf_counter()
        with self._conn() as conn:
            hit = repo.llm_cache_get(conn, key)
        if hit:
            return LLMResult(hit[0], self.inner.model, self.inner.provider, hit[1], hit[2],
                             (time.perf_counter() - t0) * 1000, cached=True)
        r = self.inner.generate(instructions, user)
        with self._conn() as conn:
            repo.llm_cache_put(conn, key, r.provider, r.model, r.text, r.input_tokens, r.output_tokens)
        return r

    def stream(self, instructions: str, user: str) -> Iterator[str]:
        key = self._key(instructions, user)
        t0 = time.perf_counter()
        with self._conn() as conn:
            hit = repo.llm_cache_get(conn, key)
        if hit:
            self.last_result = LLMResult(hit[0], self.inner.model, self.inner.provider, hit[1], hit[2],
                                         (time.perf_counter() - t0) * 1000, cached=True)
            yield hit[0]
            return
        yield from self.inner.stream(instructions, user)
        r = self.inner.last_result
        with self._conn() as conn:
            repo.llm_cache_put(conn, key, r.provider, r.model, r.text, r.input_tokens, r.output_tokens)
        self.last_result = r


@lru_cache(maxsize=1)
def get_llm():
    """The configured client (not cached-wrapped; CachedLLM needs a connection)."""
    s = get_settings()
    if s.llm_provider == "fake":
        return FakeLLM()
    if s.llm_provider != "openai":
        raise ValueError(f"LLM_PROVIDER must be 'openai' or 'fake', not {s.llm_provider!r}")
    key = s.openai_api_key.get_secret_value() if s.openai_api_key else ""
    if not key.strip():
        raise MissingAPIKey("LLM_PROVIDER=openai but OPENAI_API_KEY is empty. Add it to .env, "
                            "or set LLM_PROVIDER=fake to run offline with the deterministic fake model.")
    return OpenAIClient(key.strip(), s.llm_model, s.llm_max_output_tokens, s.llm_temperature, s.llm_timeout_s)
