"""
Settings and configuration management.
Loads environment variables from .env file.
"""

import json
from typing import Any
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
from functools import lru_cache


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""
    
    # API Configuration
    app_name: str = "AI Hallucination Detection Backend"
    app_version: str = "0.1.0"
    app_debug: bool = False
    
    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    
    # LLM Configuration
    llm_provider: str = "gemini"  # "gemini", "openai", "groq", "grok", or "anthropic"
    llm_api_key: str = ""
    grok_api_key: str = ""
    llm_model: str = "gemini-2.0-flash"  # or "gpt-4", "gpt-3.5-turbo"
    llm_api_base: str = ""
    
    # External API Keys
    serpapi_key: str = ""
    wikipedia_api_enabled: bool = True
    
    # Caching
    cache_enabled: bool = True
    cache_ttl_seconds: int = 3600

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = True   # Set False to force in-memory fallback

    # CORS — restrict to extension origin in production.
    # Set ALLOWED_ORIGINS=chrome-extension://<id> in .env when Dev 1 ships auth.
    # Comma-separated list e.g.: chrome-extension://abc123,https://yourdomain.com
    allowed_origins: Any = ["*"]

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_allowed_origins(cls, v: Any) -> list[str]:
        """Parse allowed origins from string, JSON array, or list."""
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return ["*"]
            if v.startswith("[") and v.endswith("]"):
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return [str(x).strip() for x in parsed]
                except Exception:
                    pass
            # Comma-separated list or single string
            return [x.strip() for x in v.split(",") if x.strip()]
        elif isinstance(v, list):
            return [str(x).strip() for x in v]
        return v

    # Evidence Configuration
    max_evidence_tokens: int = 2000
    max_claims_per_request: int = 3

    # ── JWT Authentication ────────────────────────────────────────────────────
    # JWT_SECRET is the shared symmetric key (HS256) used by the token issuer
    # (e.g. Supabase / Firebase) to sign tokens.  We only *verify* here —
    # we never mint tokens ourselves.
    jwt_secret: str = Field(
        default="",
        description="Shared secret for HS256 JWT verification (set via JWT_SECRET env var)",
    )
    jwt_algorithm: str = Field(
        default="HS256",
        description="JWT signing algorithm expected on incoming tokens",
    )
    jwt_expiry_seconds: int = Field(
        default=3600,
        description="Tolerated token lifetime in seconds (used for leeway checks)",
    )

    # ── MongoDB (per-user history) ────────────────────────────────────────────
    # Kept strictly separate from Redis — Redis stays global/anonymous for
    # maximum cache-hit rates; Mongo is the per-user audit store.
    mongodb_url: str = Field(
        default="mongodb://localhost:27017",
        description="Async Motor / PyMongo connection URI",
    )
    database_name: str = Field(
        default="aimatrix_db",
        description="MongoDB database name for per-user history",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore"
    )


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
