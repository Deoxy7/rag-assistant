"""Phase 11: the eval harness — metric arithmetic on hand-computed examples, the golden set's labels, the runner.

The worked examples here are the ones derived step by step in docs/15-eval-harness.md §6.
"""

import json
import math

import pytest

from eval import golden
from eval.metrics import abstention as ab
from eval.metrics import judge as jd
from eval.metrics import retrieval as rm
from eval.metrics.stats import bootstrap_ci, sign_test
from eval.golden import Span


def C(cid, doc, s, e):
    return rm.ChunkRef(cid, doc, s, e)


# One evidence item, quote at chars 100–200 of DOC (two occurrences: 100–200 and 900–1000).
ITEM = (Span("DOC", 100, 200, 3), Span("DOC", 900, 1000, 9))


@pytest.mark.parametrize("chunk, grade", [
    (C(1, "DOC", 0, 500), 2),        # contains the whole quote
    (C(2, "DOC", 150, 600), 1),      # contains 50 of 100 chars: half → partial
    (C(3, "DOC", 160, 600), 0),      # 40 of 100: not enough
    (C(4, "DOC", 850, 1200), 2),     # the second occurrence counts too
    (C(5, "OTHER", 0, 500), 0),      # right offsets, wrong document
])
def test_span_grades(chunk, grade):
    assert rm.item_grade(chunk, ITEM) == grade


def test_worked_example_from_the_doc():
    # Two-item (multi-hop) question: item A in doc X 100–200, item B in doc Y 50–150.
    A = (Span("X", 100, 200, 1),)
    B = (Span("Y", 50, 150, 1),)
    ranked = [C(10, "X", 900, 1500),     # 1: irrelevant
              C(11, "X", 0, 400),        # 2: contains A → grade 2
              C(12, "Y", 100, 600),      # 3: half of B → grade 1
              C(13, "Z", 0, 100)]        # 4: irrelevant
    ideal = [2, 2]                        # best case: a full chunk for A and one for B
    s3 = rm.score(ranked, (A, B), k=3, ideal_grades=ideal)
    assert s3.hit == 1.0
    assert s3.recall == 1.0                              # both items covered by the top 3
    assert s3.precision == pytest.approx(2 / 3)
    assert s3.rr == 0.5 and s3.first_rank == 2
    dcg = (2 ** 2 - 1) / math.log2(3) + (2 ** 1 - 1) / math.log2(4)       # 3/1.585 + 1/2 = 2.393
    idcg = (2 ** 2 - 1) / math.log2(2) + (2 ** 2 - 1) / math.log2(3)      # 3 + 1.893 = 4.893
    assert s3.ndcg == pytest.approx(dcg / idcg) and round(s3.ndcg, 3) == 0.489
    s1 = rm.score(ranked, (A, B), k=1, ideal_grades=ideal)
    assert (s1.hit, s1.recall, s1.precision, s1.ndcg) == (0.0, 0.0, 0.0, 0.0)
    s2 = rm.score(ranked, (A, B), k=2, ideal_grades=ideal)
    assert s2.recall == 0.5                              # only A covered


def test_nothing_relevant_retrieved():
    s = rm.score([C(1, "X", 0, 10)], ((Span("X", 500, 600, 2),),), k=5, ideal_grades=[2])
    assert (s.hit, s.recall, s.rr, s.ndcg, s.first_rank) == (0.0, 0.0, 0.0, 0.0, None)


def test_abstention_counts():
    refused = [True, False, False, True, True]
    answerable = [True, True, True, False, False]
    sc = ab.abstention(refused, answerable)
    assert (sc.n_answerable, sc.n_unanswerable) == (3, 2)
    assert sc.precision == pytest.approx(2 / 3)          # 3 refusals, 2 right
    assert sc.recall == 1.0 and sc.false_answer_rate == 0.0
    assert sc.false_refusal_rate == pytest.approx(1 / 3)


def test_auroc_and_sweep():
    assert ab.auroc([3, 4, 5], [1, 2]) == 1.0
    assert ab.auroc([1, 2], [3, 4, 5]) == 0.0
    assert ab.auroc([2, 3], [2, 1]) == pytest.approx((0.5 + 1 + 1 + 1) / 4)   # one tie counts ½
    sweep = dict((t, (fr, rec)) for t, fr, rec, _ in ab.threshold_sweep([3, 4, 5], [1, 2]))
    assert sweep[3] == (0.0, 1.0)                        # refuse below 3: every unanswerable, no answerable


def test_sign_test_and_bootstrap():
    w, l, p = sign_test([1, 1, 1, 1, 0, 0], [0, 0, 0, 0, 1, 1])
    assert (w, l) == (4, 2) and p == pytest.approx(22 / 64 * 2)        # = 0.6875
    lo, hi = bootstrap_ci([0.0] * 5 + [1.0] * 5)
    assert lo < 0.5 < hi and bootstrap_ci([1.0] * 4) == (1.0, 1.0)


class ScriptJudge:
    """Returns canned JSON keyed by which prompt is asked."""
    model = "script-judge"

    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def generate(self, instructions, user):
        from app.generate.llm import LLMResult
        key = next(k for k in ("claims", "score", "useful", "verdict") if f'"{k}"' in instructions)
        self.calls.append(key)
        return LLMResult(self.replies[key], self.model, "script", 0, 0, 0.0)


def test_judge_scores_and_parsing():
    j = ScriptJudge({"claims": 'Sure! {"claims": [{"claim": "a", "supported": true}, {"claim": "b", "supported": false}]}',
                     "score": '{"score": 4}', "useful": '{"useful": [false, true, true]}',
                     "verdict": '{"verdict": "partial"}'})
    s = jd.judge_answer(j, "q", "answer [1]", False, ["s1"], "ref", retrieved=["s1", "s2", "s3"], judge_context=True)
    assert s.faithfulness == 0.5 and s.answer_relevance == 0.75 and s.correctness == 0.5
    assert s.context_precision == pytest.approx((1 / 2 + 2 / 3) / 2)   # useful at ranks 2 and 3
    assert s.parse_errors == 0


def test_faithfulness_is_judged_against_the_cited_sources_only():
    seen = []

    class Recorder(ScriptJudge):
        def generate(self, instructions, user):
            seen.append(user)
            return super().generate(instructions, user)
    j = Recorder({"claims": '{"claims": []}', "score": '{"score": 5}', "useful": "{}", "verdict": '{"verdict": "correct"}'})
    s = jd.judge_answer(j, "q", "answer [2]", False, ["CITED TEXT"], "ref", retrieved=["other", "CITED TEXT"])
    assert "CITED TEXT" in seen[0] and "other" not in seen[0]
    assert "useful" not in j.calls and s.context_precision is None      # LLM context precision is opt-in
    s = jd.judge_answer(j, "q", "uncited answer", False, [], "ref")
    assert "(none cited)" in seen[-3]


def test_judge_skips_faithfulness_for_refusals_and_counts_bad_json():
    j = ScriptJudge({"claims": "{}", "score": "no json here", "useful": '{"useful": [true]}', "verdict": "{}"})
    s = jd.judge_answer(j, "q", "I can't answer", True, [], None, retrieved=["s1", "s2"], judge_context=True)
    assert "claims" not in j.calls and "verdict" not in j.calls
    assert s.faithfulness is None and s.answer_relevance is None
    assert s.context_precision is None and s.parse_errors == 2       # bad JSON + wrong-length list


def test_label_context_precision():
    A = (Span("X", 100, 200, 1),)
    ranked = [C(1, "X", 900, 1500), C(2, "X", 0, 400), C(3, "Y", 0, 10), C(4, "X", 120, 600)]
    # relevant at ranks 2 and 4 → (1/2 + 2/4) / 2 = 0.5
    assert rm.context_precision(ranked, (A,)) == pytest.approx(0.5)
    assert rm.context_precision([C(9, "Z", 0, 5)], (A,)) == 0.0


# --- the golden set itself (needs the ingested database) ---------------------------------------------

def test_every_golden_label_resolves_to_stored_text(conn):
    qs = golden.load(conn)
    assert len(qs) >= 50
    types = {q.type for q in qs}
    assert {"factual", "table", "exact_token", "multi_hop", "unanswerable"} <= types
    assert all(len(q.items) >= 2 for q in qs if q.type == "multi_hop")
    for q in qs:
        for item in q.items:
            for sp in item:
                text = conn.execute("SELECT substr(canonical_text, %s, %s) FROM documents WHERE doc_key = %s",
                                    (sp.char_start + 1, sp.char_end - sp.char_start, sp.doc_key)).fetchone()[0]
                assert text and len(text) == sp.char_end - sp.char_start


def test_bad_labels_are_rejected(conn, tmp_path):
    bad = tmp_path / "g.jsonl"
    bad.write_text(json.dumps({"id": "X1", "type": "factual", "question": "q", "answer": "a",
                               "evidence": [[{"doc": "AMD_2022_10K", "quote": "this sentence is not in the filing"}]]}) + "\n")
    with pytest.raises(golden.LabelError, match="quote not found"):
        golden.load(conn, bad)
    bad.write_text(json.dumps({"id": "X2", "type": "unanswerable", "question": "q", "answer": None,
                               "evidence": [[{"doc": "AMD_2022_10K", "quote": "Total net revenue"}]]}) + "\n")
    with pytest.raises(golden.LabelError, match="unanswerable"):
        golden.load(conn, bad)


def test_results_are_never_overwritten(tmp_path, monkeypatch):
    from eval import run
    monkeypatch.setattr(run, "RESULTS", tmp_path)
    p1, f1 = run.open_exclusive("20261002T000000Z_x", ".json")
    f1.write("first")
    f1.close()
    p2, f2 = run.open_exclusive("20261002T000000Z_x", ".json")
    f2.close()
    assert p1.name == "20261002T000000Z_x.json" and p2.name == "20261002T000000Z_x-2.json"
    assert p1.read_text() == "first"
