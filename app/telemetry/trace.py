"""Stage timings for one request, collected without threading a parameter through every layer.

    tr = Trace()
    with activate(tr):
        with stage("retrieve.vector"):
            ...
    tr.timings_ms  # {"retrieve.vector": 3.9, …}

`stage()` records into the trace that is *active in the current context* (a
contextvar), so the retrievers, embedder and reranker can time themselves
without knowing who called them. With no active trace, `stage()` is a no-op.
Contextvars are per thread/task: FastAPI runs a sync endpoint (or one step of a
streaming generator) in one worker thread, and the trace is activated and
reset inside that same call, so concurrent requests never see each other's
timings.
"""

import contextvars
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

_current: contextvars.ContextVar["Trace | None"] = contextvars.ContextVar("trace", default=None)


@dataclass
class Trace:
    timings_ms: dict[str, float] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)

    def add(self, name: str, ms: float) -> None:
        # The same stage can run more than once per request (e.g. two keyword searches); sum them.
        self.timings_ms[name] = round(self.timings_ms.get(name, 0.0) + ms, 2)

    def count(self, name: str, n: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + n


def current() -> "Trace | None":
    return _current.get()


@contextmanager
def activate(trace: Trace):
    token = _current.set(trace)
    try:
        yield trace
    finally:
        _current.reset(token)


@contextmanager
def stage(name: str):
    tr = _current.get()
    if tr is None:
        yield
        return
    t0 = time.perf_counter()
    try:
        yield
    finally:
        tr.add(name, (time.perf_counter() - t0) * 1000)


def count(name: str, n: int = 1) -> None:
    tr = _current.get()
    if tr is not None:
        tr.count(name, n)
