"""Phase 13: stage tracing, cost accounting, JSON logs."""

import json
import logging
import threading

import pytest

from app.telemetry import logs
from app.telemetry.cost import Price, cost
from app.telemetry.trace import Trace, activate, count, current, stage


def test_stage_records_into_the_active_trace_and_is_a_noop_without_one():
    with stage("orphan"):
        pass                                   # no active trace: nothing happens, no error
    tr = Trace()
    with activate(tr):
        with stage("a"):
            with stage("a.inner"):
                pass
        with stage("a"):                        # repeated stage: summed
            pass
        count("hits", 2)
    assert set(tr.timings_ms) == {"a", "a.inner"} and tr.counters == {"hits": 2}
    assert current() is None                    # reset after the block


def test_traces_do_not_leak_between_threads():
    seen = {}

    def worker(name):
        tr = Trace()
        with activate(tr):
            with stage(name):
                pass
        seen[name] = set(tr.timings_ms)
    ts = [threading.Thread(target=worker, args=(f"t{i}",)) for i in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert seen == {f"t{i}": {f"t{i}"} for i in range(4)}


def test_cost_list_vs_billed_vs_cached():
    p = Price(0.80, 4.00, free_tier=True)
    c = cost(1548, 100, p)
    assert c.list_usd == pytest.approx(0.0016384) and c.billed_usd == 0.0     # the doc's worked example
    assert cost(1548, 100, Price(0.80, 4.00, free_tier=False)).billed_usd == pytest.approx(0.0016384)
    assert cost(1548, 100, p, cached=True).list_usd == 0.0


def test_json_log_lines_carry_fields(capsys):
    logs.configure("json", "INFO")
    logging.getLogger("rag.test").info("answer", extra={"fields": {"request_id": "abc", "list_usd": 0.001}})
    line = capsys.readouterr().err.strip().splitlines()[-1]
    obj = json.loads(line)
    assert obj["event"] == "answer" and obj["request_id"] == "abc" and obj["level"] == "INFO" and obj["ts"].endswith("Z")
