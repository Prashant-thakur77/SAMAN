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

    #: Set the Secure flag on the session cookie. Off by default because the
    #: demo is served over plain HTTP on localhost, where a Secure cookie would
    #: never be sent at all; any real deployment must turn it on.
    saman_secure_cookies: bool = False

    #: Force the §0.4 fallback engines even when the optional accelerators are
    #: installed. Two uses: exercising the degraded path in CI without
    #: uninstalling anything, and demonstrating graceful degradation live.
    saman_disable_optional: bool = False

    #: Which Tier-1 engine to use: "auto" takes splink when it is installed
    #: (§0.4), "splink" and "rapidfuzz" pin one. Pinning matters for a live
    #: demo, where "whichever happens to be installed on this laptop" is not an
    #: answer, and for measuring the two against each other on one machine.
    saman_tier1_engine: str = "auto"

    # Optional Tier-3 LLM. Unset => deterministic adjudicator + templated Copilot.
    ollama_url: str | None = None
    ollama_model: str = "qwen2.5:3b"

    # ERP adapter (docs/sap-integration.md). "mock" ships with the demo; "rfc"
    # needs pyrfc and the SAP NetWeaver RFC SDK and falls back to the mock,
    # with a note at /api/health, when either is missing.
    saman_erp_adapter: str = "mock"
    sap_ashost: str | None = None
    sap_sysnr: str = "00"
    sap_client: str = "100"
    sap_user: str | None = None
    sap_passwd: str | None = None
    sap_cnmc_field: str = "ZZ_CNMC"
    sap_supersedes_field: str = "ZZ_SUPERSEDES"
    #: Machine access for the SAP-side hook: "email=key,email2=key2". A key acts
    #: as the named user, so every call is attributed and scoped like a person's.
    saman_api_keys: str = ""

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
        """Sovereign mode wins over OLLAMA_URL (spec 6.13)."""
        return bool(self.ollama_url) and not sovereign_mode()

    def model_post_init(self, _context) -> None:
        # OLLAMA_URL unset means "whatever is on this machine": a local Ollama
        # answering on its default port is used, and nothing else is ever
        # tried. Set SAMAN_OLLAMA_AUTODETECT=false to keep the deterministic
        # path even when one is present.
        if self.ollama_url is None and self.saman_ollama_autodetect:
            self.ollama_url = _local_ollama()

    saman_ollama_autodetect: bool = True


def _local_ollama() -> str | None:
    """http://localhost:11434 if something is listening there, else None."""
    import socket

    try:
        with socket.create_connection(("127.0.0.1", 11434), timeout=0.3):
            return "http://127.0.0.1:11434"
    except OSError:
        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()


#: A runtime toggle of sovereign mode, set from /admin (spec 6.13).
#:
#: It cannot live on the cached Settings object: capability detection clears
#: that cache to re-read the environment, which would silently discard the
#: operator's choice moments after they made it. None means "no override --
#: use whatever the environment says".
_SOVEREIGN_OVERRIDE: bool | None = None


def sovereign_mode() -> bool:
    if _SOVEREIGN_OVERRIDE is not None:
        return _SOVEREIGN_OVERRIDE
    return get_settings().saman_sovereign_mode


def set_sovereign_mode(enabled: bool | None) -> bool:
    """Set, or with None clear, the runtime override. Returns the new value."""
    global _SOVEREIGN_OVERRIDE
    _SOVEREIGN_OVERRIDE = enabled
    return sovereign_mode()
