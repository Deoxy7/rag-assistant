"""Application settings — the single source of truth for configuration.

Every tunable value in the project is declared here and read from environment
variables (or the repo's .env file). No other module reads os.environ directly,
so "what can be configured, and what is its default?" has exactly one answer.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process; every caller shares the same object."""
    return Settings()
