"""Application settings loaded from the environment."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings sourced from environment variables or ``.env``."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    github_token: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    llm_model: str | None = None
    llm_zdr_enabled: bool = False
    cache_ttl_seconds: int = Field(default=3600, gt=0)
    log_level: str = "INFO"
