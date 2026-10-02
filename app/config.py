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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process; every caller shares the same object."""
    return Settings()
