"""The UI's only way into the system: HTTP calls to the FastAPI app (never `import app`).

Keeping the UI on the public API means it exercises exactly what any other
client would. Validation, refusal gating, the output policy and the request
log all apply to it, and it could be replaced by a React app without touching
the backend. tests/test_ui.py checks that nothing in ui/ imports app/.
"""

import json
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

import httpx

DEFAULT_URL = os.environ.get("RAG_API_URL", "http://127.0.0.1:8000")


class APIError(Exception):
    """A non-2xx response or an in-band `error` event, with the API's error code."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"{status} {code}: {message}")
        self.status, self.code, self.message = status, code, message


def raise_for_error(r: httpx.Response) -> None:
    if r.status_code >= 400:
        try:
            body = r.json()
            raise APIError(r.status_code, body.get("error", "http_error"), body.get("message", r.text))
        except (ValueError, AttributeError):
            raise APIError(r.status_code, "http_error", r.text[:200]) from None


def parse_sse(lines: Iterator[str]) -> Iterator[tuple[str, object]]:
    """(event, JSON data) for each Server-Sent Event; comments (":…") and ids are skipped.

    An event ends at a blank line; its `data:` lines are joined with newlines,
    per the SSE spec. The API sends one JSON value per event.
    """
    event, data = "message", []
    for line in lines:
        if line == "":
            if data:
                yield event, json.loads("\n".join(data))
            event, data = "message", []
        elif line.startswith(":"):
            continue
        else:
            name, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if name == "event":
                event = value
            elif name == "data":
                data.append(value)
    if data:
        yield event, json.loads("\n".join(data))


@dataclass
class StreamTimings:
    """Client-side clock, from sending the request: what the user actually waits for."""
    sources_ms: float | None = None
    first_delta_ms: float | None = None
    done_ms: float | None = None


@dataclass
class Client:
    base_url: str = DEFAULT_URL
    http: httpx.Client | None = None
    timeout_s: float = 120.0
    timings: StreamTimings = field(default_factory=StreamTimings)

    def __post_init__(self):
        if self.http is None:
            self.http = httpx.Client(base_url=self.base_url, timeout=self.timeout_s)

    def health(self) -> dict:
        r = self.http.get("/health")
        raise_for_error(r)
        return r.json()

    def documents(self) -> list[dict]:
        r = self.http.get("/documents")
        raise_for_error(r)
        return r.json()

    def stats(self, hours: float = 24) -> dict:
        r = self.http.get("/stats", params={"hours": hours})
        raise_for_error(r)
        return r.json()

    def page_png(self, chunk_id: int, page: int | None = None, dpi: int = 110) -> bytes:
        params = {"dpi": dpi} | ({"page": page} if page else {})
        r = self.http.get(f"/chunks/{chunk_id}/page.png", params=params)
        raise_for_error(r)
        return r.content

    def stream(self, question: str, companies: list[str] | None = None, fiscal_years: list[int] | None = None,
               k: int | None = None) -> Iterator[tuple[str, object]]:
        """Yields ("sources", [...]), ("delta", str)…, then ("answer", {...}); raises APIError on failure."""
        body = {"question": question, "companies": companies or None, "fiscal_years": fiscal_years or None, "k": k}
        self.timings = StreamTimings()
        t0 = time.perf_counter()
        with self.http.stream("POST", "/query/stream", json={k_: v for k_, v in body.items() if v is not None}) as r:
            if r.status_code >= 400:
                r.read()
                raise_for_error(r)
            for event, data in parse_sse(r.iter_lines()):
                now = (time.perf_counter() - t0) * 1000
                if event == "sources":
                    self.timings.sources_ms = now
                elif event == "delta" and self.timings.first_delta_ms is None:
                    self.timings.first_delta_ms = now
                elif event == "error":
                    raise APIError(data.get("status", 500), data.get("error", "error"), data.get("message", ""))
                elif event == "answer":
                    self.timings.done_ms = now
                yield event, data
