"""Application settings — the single source of truth for configuration.

Every tunable value in the project is declared here and read from environment
variables (or the repo's .env file). No other module reads os.environ directly,
so "what can be configured, and what is its default?" has exactly one answer.
"""

from functools import lru_cache
from pathlib import Path

from typing import Literal

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

    # --- Generation (Phase 9; Gemini since 2026-10-02; Flash-Lite generator + Groq judge since 2026-10-03) ---
    # Any OpenAI-compatible Chat Completions endpoint. Provider picks which key
    # setting is read ("gemini" → GEMINI_API_KEY, "openai" → OPENAI_API_KEY, "groq" → GROQ_API_KEY);
    # base URL and models are plain settings, so switching provider is a .env edit.
    # "fake" = deterministic offline stand-in. No silent fallback: a real provider
    # without its key is an error, so a demo can't quietly run on the fake.
    # Generator on Groq since 2026-10-03 (user's decision): the Gemini project returns 402 "prepayment
    # credits are depleted" for every model (T-054). Gemini stays one .env edit away (.env.example).
    llm_provider: str = "groq"
    llm_base_url: str | None = "https://api.groq.com/openai/v1"   # None = OpenAI; Gemini: …/v1beta/openai/
    # SecretStr: printing settings shows '**********', never the key.
    gemini_api_key: SecretStr | None = Field(default=None, repr=False)
    openai_api_key: SecretStr | None = Field(default=None, repr=False)
    groq_api_key: SecretStr | None = Field(default=None, repr=False)
    # Models picked 2026-10-02 from models.list() on the user's key plus a live probe:
    # gemini-3.8-flash / 3.7-flash returned 503 "high demand", gemini-2.5-* 404 "no longer
    # available to new users"; gemini-3.5-flash (1.5 s) and gemini-3.5-flash-lite (0.8 s) answered.
    # Dated aliases like *-latest are avoided: they move, and evals must be reproducible.
    # History: gemini-3.5-flash (2026-10-02) → gemini-3.5-flash-lite (free tier allowed only 20 Flash
    # requests/day, T-052) → qwen/qwen3.8-27b on Groq (Gemini 402, T-054). Picked from the Groq key's
    # models.list(): the judge is openai/gpt-oss-120b, so the generator is the other general model
    # family available there (Alibaba's Qwen), keeping generator and judge in different families.
    llm_model: str = "qwen/qwen3.8-27b"
    # Gemini 3.x Flash counts its hidden "thinking" tokens against this cap (T-046).
    llm_max_output_tokens: int = 2048
    # None = don't send. Flash-Lite rejects reasoning_effort="none" with HTTP 400 (T-048).
    llm_reasoning_effort: str | None = None
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
    # --- Phase 14: security (docs/18) ---
    prompt_template: Literal["1", "2"] = "2"   # "2" fences sources and defuses forged headers; "1" = Phases 9–13
    injection_filter: Literal["drop", "flag", "off"] = "drop"   # sources that address the model
    output_policy: bool = True           # strip links, images and HTML from answers (and streamed deltas)
    # USD per 1M tokens at the provider's *paid list price* (Groq models page, 2026-10-03:
    # qwen/qwen3.8-27b $0.80 in / $4.00 out). With *_free_tier true the billed cost is 0 but the
    # list cost is still reported, as the number to plan with. Free-tier limits per model: 30 RPM,
    # 1K RPD, 8K TPM, 200K TPD.
    llm_price_input_per_m: float = 0.80
    llm_price_output_per_m: float = 4.00
    llm_free_tier: bool = True
    # Eval judge: its own provider, so it can be a different model *family* from the generator
    # (a Gemini judge grading a Gemini generator shares its blind spots and self-preference).
    # Groq's free tier, OpenAI-compatible; model picked from the key's models.list() on 2026-10-03.
    # Free-tier limits per model: 30 RPM, 1K RPD, 8K TPM, 200K TPD (Groq rate-limit docs).
    llm_judge_provider: str = "groq"
    llm_judge_base_url: str | None = "https://api.groq.com/openai/v1"
    llm_judge_model: str = "openai/gpt-oss-120b"
    llm_judge_max_output_tokens: int = 1024
    # gpt-oss reasons before answering; "low" keeps judge calls inside the free tier's token budget.
    llm_judge_reasoning_effort: str | None = "low"
    llm_judge_price_input_per_m: float = 0.15    # openai/gpt-oss-120b on Groq, paid list price
    llm_judge_price_output_per_m: float = 0.60
    llm_judge_free_tier: bool = True

    # --- Observability (Phase 13) ---
    log_format: str = "json"             # "json" (one object per line) | "text"
    log_level: str = "INFO"
    request_log_enabled: bool = True     # one row per /query request in Postgres (feeds GET /stats)

    @field_validator("llm_base_url", "llm_judge_base_url", "llm_reasoning_effort", "llm_judge_reasoning_effort",
                     "llm_temperature", mode="before")
    @classmethod
    def blank_means_unset(cls, v):
        # In .env, `LLM_BASE_URL=` (empty) must mean "use the SDK default", not the URL "".
        return None if isinstance(v, str) and not v.strip() else v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process; every caller shares the same object."""
    return Settings()
