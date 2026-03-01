"""Application settings loaded from environment variables.

All configuration is declared here as a single ``Settings`` object backed by
``pydantic-settings``.  The ``FADR_API_KEY`` is stored as a ``SecretStr`` to
prevent accidental serialisation to logs or error messages.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # Allow the settings to be constructed without a .env file in tests.
        env_ignore_empty=False,
    )

    # ------------------------------------------------------------------ Fadr
    fadr_api_key: SecretStr
    fadr_base_url: str = "https://api.fadr.com"
    fadr_timeout_s: float = 30.0
    fadr_poll_interval_s: float = 5.0
    fadr_poll_timeout_s: float = 300.0
    fadr_max_retries: int = 3

    # ---------------------------------------------------------------- Server
    log_level: str = "INFO"
    allowed_audio_schemes: str = "https"
    max_audio_size_mb: int = 100

    # ---------------------------------------------------------------- Derived
    @property
    def allowed_schemes_set(self) -> frozenset[str]:
        return frozenset(s.strip().lower() for s in self.allowed_audio_schemes.split(","))

    @property
    def max_audio_size_bytes(self) -> int:
        return self.max_audio_size_mb * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance (cached after first call)."""
    return Settings()
