"""LLM-as-judge metrics: faithfulness, answer relevance, context precision, correctness.

The judge is any client with .generate(instructions, user) (app/generate/llm.py),
normally wrapped in CachedLLM so a re-run costs nothing and returns the same
verdicts. Each prompt asks for JSON; parse failures are counted, never guessed.

    faithfulness       claims supported by the sources the answer cites / claims made
    answer_relevance   does the answer address the question?  score 1–5 → (s − 1) / 4
    context_precision  per retrieved chunk "useful for answering?"; averaged precision@i
                       over the positions i of useful chunks (rank-aware, RAGAS-style). Only with
                       judge_context=True: where golden labels exist, eval.run computes it from the
                       labels instead (exact, free; metrics/retrieval.py context_precision)
    correctness        correct / partially / incorrect vs the reference answer → 1 / 0.5 / 0
"""

import json
import re
from dataclasses import dataclass

FAITHFULNESS = """You check whether an answer is supported by source passages.
Split the ANSWER into its factual claims (numbers, names, dates, comparisons). For each claim decide whether the SOURCES state it or it follows by simple arithmetic from them.
Reply with JSON only: {"claims": [{"claim": "...", "supported": true|false}]}. An answer that only declines to answer has no claims."""

RELEVANCE = """You rate whether an answer addresses a question, ignoring whether it is correct.
5 = directly and completely answers it; 3 = partially; 1 = does not address it. A refusal to answer scores 1.
Reply with JSON only: {"score": 1-5}"""

CONTEXT = """You judge which retrieved passages would help answer a question.
For each numbered PASSAGE decide if it contains information needed to answer the QUESTION.
Reply with JSON only: {"useful": [true|false, ...]} with one entry per passage, in order."""

CORRECTNESS = """You grade an answer against a reference answer for a question about company filings.
"correct" = same facts (numbers may be rounded or in different units); "partial" = some right, some missing or wrong; "incorrect" otherwise. A refusal is "incorrect".
Reply with JSON only: {"verdict": "correct"|"partial"|"incorrect"}"""

JSON_OBJECT = re.compile(r"\{.*\}", re.S)


class JudgeParseError(ValueError):
    pass


def parse(text: str) -> dict:
    m = JSON_OBJECT.search(text)
    if not m:
        raise JudgeParseError(f"no JSON object in judge output: {text[:80]!r}")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise JudgeParseError(str(e)) from None


@dataclass(frozen=True)
class JudgeScores:
    faithfulness: float | None
    answer_relevance: float | None
    context_precision: float | None
    correctness: float | None
    parse_errors: int


def average_precision(useful: list[bool]) -> float | None:
    hits, total = 0, 0.0
    for i, u in enumerate(useful, start=1):
        if u:
            hits += 1
            total += hits / i
    return total / hits if hits else 0.0


def judge_answer(judge, question: str, answer: str, refused: bool, cited: list[str], reference: str | None,
                 closed_book: bool = False, retrieved: list[str] | None = None,
                 judge_context: bool = False) -> JudgeScores:
    """cited: texts of the sources the answer cites (faithfulness is judged against these).
    retrieved: every passage the model was shown (only for the LLM-judged context precision).
    closed_book=True: no sources, so faithfulness and context precision are not applicable (None)."""
    errors = 0

    def numbered(texts):
        return "\n\n".join(f"PASSAGE {i + 1}:\n{s}" for i, s in enumerate(texts))

    def ask(instructions, user):
        nonlocal errors
        try:
            return parse(judge.generate(instructions, user).text)
        except JudgeParseError:
            errors += 1
            return None

    faith = None
    if not refused and not closed_book:
        # Judged against the sources the answer cites: an answer that cites nothing has
        # nothing to support its claims, so its supported share is 0 (not skipped).
        r = ask(FAITHFULNESS, f"SOURCES:\n{numbered(cited) if cited else '(none cited)'}\n\nANSWER:\n{answer}")
        if r is not None:
            claims = r.get("claims", [])
            faith = (sum(bool(c.get("supported")) for c in claims) / len(claims)) if claims else None
    r = ask(RELEVANCE, f"QUESTION:\n{question}\n\nANSWER:\n{answer}")
    rel = (min(5, max(1, int(r["score"]))) - 1) / 4 if r and "score" in r else None
    ctx = None
    if judge_context and not closed_book and retrieved:
        r = ask(CONTEXT, f"QUESTION:\n{question}\n\n{numbered(retrieved)}")
        if r and isinstance(r.get("useful"), list) and len(r["useful"]) == len(retrieved):
            ctx = average_precision([bool(x) for x in r["useful"]])
        elif r is not None:
            errors += 1
    corr = None
    if reference is not None:
        r = ask(CORRECTNESS, f"QUESTION:\n{question}\n\nREFERENCE:\n{reference}\n\nANSWER:\n{answer}")
        corr = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}.get(r.get("verdict")) if r else None
    return JudgeScores(faith, rel, ctx, corr, errors)
