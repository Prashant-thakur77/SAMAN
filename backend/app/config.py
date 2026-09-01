"""Runtime configuration for SAMAN.

Every setting has a default that keeps the platform fully offline (spec 9).
Only ``OLLAMA_URL`` can introduce a network call, it is unset by default and
always points at localhost.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# repo root = backend/app/config.py -> backend/app -> backend -> saman
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=(REPO_ROOT / ".env"),
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "SAMAN"
    app_long_name: str = "Standardised Asset & Material Analysis Network"
    tagline: str = "One Nation, One Material Code"

    saman_db_path: str = "./data/app.db"
    saman_secret_key: str = "saman-dev-secret-change-me"
    saman_sovereign_mode: bool = False

    # Optional Tier-3 LLM. Unset => deterministic adjudicator + templated Copilot.
    ollama_url: str | None = None
    ollama_model: str = "qwen2.5:7b"

    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @property
    def db_file(self) -> Path:
        p = Path(self.saman_db_path)
        return p if p.is_absolute() else (REPO_ROOT / p).resolve()

    @property
    def database_url(self) -> str:
        self.db_file.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{self.db_file}"

    @property
    def llm_enabled(self) -> bool:
        """Sovereign mode wins over OLLAMA_URL (spec 5.12)."""
        return bool(self.ollama_url) and not self.saman_sovereign_mode


@lru_cache
def get_settings() -> Settings:
    return Settings()
