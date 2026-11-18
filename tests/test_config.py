"""Settings tests."""

from __future__ import annotations

import pytest

from app.config import Settings

_ENV_VARS = (
    "GITHUB_TOKEN",
    "OPENROUTER_API_KEY",
    "LLM_MODEL",
    "LLM_ZDR_ENABLED",
    "CACHE_TTL_SECONDS",
    "LOG_LEVEL",
)


def test_settings_loads_environment(settings: Settings) -> None:
    """Environment values populate settings without exposing secrets in repr."""
    assert settings.github_token is not None
    assert settings.github_token.get_secret_value() == "test-github-token"
    assert settings.cache_ttl_seconds == 60
    assert settings.log_level == "DEBUG"
    assert "test-github-token" not in repr(settings.github_token)


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defaults apply when no environment values are present."""
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)
    assert settings.github_token is None
    assert settings.openrouter_api_key is None
    assert settings.llm_model is None
    assert settings.llm_zdr_enabled is False
    assert settings.cache_ttl_seconds == 3600
    assert settings.log_level == "INFO"
