"""Settings behave the way docs/03-environment-and-infra.md promises."""

import pytest
from pydantic import ValidationError

from app.config import REPO_ROOT, Settings


def test_env_file_path_does_not_depend_on_the_working_directory():
    assert Settings.model_config["env_file"] == REPO_ROOT / ".env"


def test_missing_password_fails_loudly(monkeypatch):
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    with pytest.raises(ValidationError, match="postgres_password"):
        Settings(_env_file=None)  # ignore .env: simulate a machine without one


def test_environment_variables_override_defaults(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "x")
    monkeypatch.setenv("POSTGRES_PORT", "6543")
    assert Settings(_env_file=None).postgres_port == 6543


def test_password_never_appears_in_repr(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "super-secret-value")
    assert "super-secret-value" not in repr(Settings(_env_file=None))
