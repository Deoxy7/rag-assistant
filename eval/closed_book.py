"""Closed-book baseline: the same questions, no retrieval, the model's own knowledge only.

It answers "how much of the system's accuracy is the documents, and how much
is the model already knowing the answer?" Large public companies' revenue and
headcount are likely in the model's training data, so a closed-book model can
score well on factual questions, but it can't cite, and it may answer
unanswerable questions from memory or guesswork instead of refusing.
"""

from app.generate.answer import REFUSAL_MESSAGE, is_refusal
from app.generate.prompt import REFUSAL_TOKEN

CLOSED_BOOK_INSTRUCTIONS = f"""You answer questions about US public companies' annual reports (SEC Form 10-K filings) from your own knowledge. No documents are provided.
Answer concisely and directly. If you do not know the answer, or the question cannot be answered from a company's 10-K filing, reply with exactly {REFUSAL_TOKEN} and nothing else."""


def answer_closed_book(llm, question: str):
    """(text shown, refused, LLMResult)."""
    r = llm.generate(CLOSED_BOOK_INSTRUCTIONS, f"Question: {question.strip()}")
    refused = is_refusal(r.text)
    return (REFUSAL_MESSAGE if refused else r.text), refused, r
