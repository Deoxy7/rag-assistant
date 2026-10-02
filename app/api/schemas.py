"""Request and response models: the API's contract, validated by pydantic and published as OpenAPI (/docs)."""

from pydantic import BaseModel, Field, field_validator

MAX_QUESTION_CHARS = 2000


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS,
                          examples=["What was AMD's net revenue in 2022?"])
    companies: list[str] | None = Field(default=None, max_length=10, examples=[["AMD"]],
                                        description="Restrict to these companies (exact names from /documents).")
    fiscal_years: list[int] | None = Field(default=None, max_length=10, examples=[[2022]])
    k: int | None = Field(default=None, ge=1, le=20, description="Chunks to retrieve; default from settings (10).")

    @field_validator("question")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("question must contain non-whitespace characters")
        return v.strip()

    @field_validator("fiscal_years")
    @classmethod
    def plausible_years(cls, v):
        if v and any(not 1990 <= y <= 2100 for y in v):
            raise ValueError("fiscal years must be between 1990 and 2100")
        return v


class CitationOut(BaseModel):
    n: int
    label: str                    # "AMD 2022 10-K, p. 43"
    chunk_id: int
    doc_key: str
    page_number: int              # PDF page (not the printed folio)
    page_end: int
    char_start: int               # offsets into the document's canonical text
    char_end: int


class SourceOut(BaseModel):
    n: int
    chunk_id: int
    doc_key: str
    company: str
    fiscal_year: int
    page_number: int
    page_end: int
    section: list[str]
    score: float                  # reranker score when reranking is on, else the fused score
    text: str


class Usage(BaseModel):
    provider: str | None
    model: str | None
    input_tokens: int
    output_tokens: int
    cached: bool
    truncated: bool = False       # the model hit its output-token cap; the answer may be cut off


class QueryResponse(BaseModel):
    request_id: str
    answer: str
    refused: bool
    refusal_reason: str | None
    citations: list[CitationOut]
    sources: list[SourceOut]
    invalid_markers: list[int]
    uncited_sentences: list[str]
    usage: Usage
    timings_ms: dict[str, float]


class DocumentOut(BaseModel):
    doc_key: str
    company: str
    ticker: str
    fiscal_year: int
    form: str
    pages: int
    chunks: int


class Health(BaseModel):
    status: str                   # "ok" | "degraded"
    database: bool
    chunk_set_id: int
    retrieval_mode: str
    rerank_enabled: bool
    llm_provider: str
    llm_model: str
    llm_ready: bool               # provider configured (key present for openai)
    detail: str | None = None


class ErrorOut(BaseModel):
    request_id: str
    error: str                    # machine-readable code
    message: str
