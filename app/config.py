"""Application settings — the single source of truth for configuration.

Every tunable value in the project is declared here and read from environment
variables (or the repo's .env file). No other module reads os.environ directly,
so "what can be configured, and what is its default?" has exactly one answer.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to the repo, not the current working directory, so that
# `pytest` run from any folder (or an IDE) still finds the same file.
REPO_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",  # .env also holds values meant only for docker compose
    )

    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_db: str = "rag"
    postgres_user: str = "rag"
    # No default: a missing password should fail loudly at startup, not later
    # as a confusing authentication error. repr=False keeps it out of logs.
    postgres_password: str = Field(repr=False)

    # --- Models (downloaded into data/models, pinned by Hugging Face commit) ---
    model_cache_dir: Path = REPO_ROOT / "data" / "models"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_model_revision: str = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
    # bge-small reads at most 512 tokens including its two special tokens
    # ([CLS] and [SEP]); anything longer is silently truncated.
    embedding_max_tokens: int = 512
    embedding_dims: int = 384
    # "auto" = Apple GPU (MPS) when available, else CPU. Measured on the M1:
    # MPS 116 chunks/s vs CPU 46, vectors equal to within 3.3e-7.
    embedding_device: str = "auto"
    embedding_batch_size: int = 64
    # bge v1.5's model card recommends this prefix for *queries* (not passages)
    # in retrieval; documents are embedded as-is.
    query_instruction: str = "Represent this sentence for searching relevant passages: "

    # --- Chunking (Phase 3; every value is an ablation lever in Phase 12) ---
    chunk_strategy: str = "structure"   # "fixed" | "recursive" | "structure"
    chunk_size: int = 256                # in embedding-model tokens
    chunk_overlap: int = 32              # in embedding-model tokens

    # --- Retrieval (Phases 5-7) ---
    retrieval_mode: str = "hybrid"       # "vector" | "keyword" | "hybrid"
    rrf_k: int = 60                      # RRF constant (Cormack et al., 2009)
    retrieval_depth: int = 50            # results taken from each retriever before fusing

    # --- Reranking (Phase 8) ---
    rerank_enabled: bool = True
    # First-stage candidates the cross-encoder re-sorts. Measured (make bench-rerank):
    # N=10 was never meaningfully worse than 20/50/100 and is half the latency of 20.
    rerank_n: int = 10
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    rerank_model_revision: str = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
    rerank_device: str = "auto"
    rerank_batch_size: int = 32
    rerank_max_length: int = 512         # (question + chunk) tokens; longer pairs are truncated

    # --- Generation (Phase 9; provider switched to Gemini on 2026-10-02) ---
    # Any OpenAI-compatible Chat Completions endpoint. Provider picks which key
    # setting is read ("gemini" → GEMINI_API_KEY, "openai" → OPENAI_API_KEY);
    # base URL and models are plain settings, so switching provider is a .env edit.
    # "fake" = deterministic offline stand-in. No silent fallback: a real provider
    # without its key is an error, so a demo can't quietly run on the fake.
    llm_provider: str = "gemini"
    llm_base_url: str | None = "https://generativelanguage.googleapis.com/v1beta/openai/"   # None = OpenAI
    # SecretStr: printing settings shows '**********', never the key.
    gemini_api_key: SecretStr | None = Field(default=None, repr=False)
    openai_api_key: SecretStr | None = Field(default=None, repr=False)
    # Models picked 2026-10-02 from models.list() on the user's key plus a live probe:
    # gemini-3.8-flash / 3.7-flash returned 503 "high demand", gemini-2.5-* 404 "no longer
    # available to new users"; gemini-3.5-flash (1.5 s) and gemini-3.5-flash-lite (0.8 s) answered.
    # Dated aliases like *-latest are avoided: they move, and evals must be reproducible.
    llm_model: str = "gemini-3.5-flash"
    # Gemini 3.x Flash counts its hidden "thinking" tokens against this cap (T-046).
    llm_max_output_tokens: int = 2048
    # "low" keeps some reasoning for calculation questions; None = don't send. Flash-Lite
    # rejects reasoning_effort="none" with HTTP 400, so the judge default is None.
    llm_reasoning_effort: str | None = "low"
    # None = don't send (some models reject a temperature parameter).
    llm_temperature: float | None = None
    llm_timeout_s: float = 60.0
    # Retries on 429 (not an empty balance) and 5xx: exponential backoff with jitter.
    llm_max_retries: int = 6
    llm_retry_base_s: float = 1.0
    llm_retry_max_s: float = 30.0
    llm_cache_enabled: bool = True
    answer_top_k: int = 10               # chunks retrieved for an answer (after rerank)
    context_token_budget: int = 3000     # o200k_base tokens of sources packed into the prompt
    context_order: str = "rank"          # "rank" (best first) | "sandwich" (best at both ends); Phase 12 ablation
    # USD per 1M tokens (Gemini pricing page, 2026-10-02, paid tier; output includes thinking
    # tokens; a free tier also exists); used for cost estimates only.
    llm_price_input_per_m: float = 1.50
    llm_price_output_per_m: float = 9.00
    # Eval judge: Flash-Lite (user's choice, 2026-10-02): cheaper and faster than the generator,
    # but a *weaker* model grading a stronger one (see card #37).
    llm_judge_model: str = "gemini-3.5-flash-lite"
    llm_judge_max_output_tokens: int = 1024
    llm_judge_reasoning_effort: str | None = None
    llm_judge_price_input_per_m: float = 0.30
    llm_judge_price_output_per_m: float = 2.50

    @field_validator("llm_base_url", "llm_reasoning_effort", "llm_judge_reasoning_effort", "llm_temperature",
                     mode="before")
    @classmethod
    def blank_means_unset(cls, v):
        # In .env, `LLM_BASE_URL=` (empty) must mean "use the SDK default", not the URL "".
        return None if isinstance(v, str) and not v.strip() else v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process; every caller shares the same object."""
    return Settings()
