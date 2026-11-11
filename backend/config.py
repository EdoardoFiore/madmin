"""
MADMIN Configuration Module

Loads settings from environment variables with type validation.
Uses Pydantic Settings for robust configuration management.
"""
import json
import os
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator
from typing import List
from functools import lru_cache

# Versione MADMIN (usata per export/import config cross-versione)
MADMIN_VERSION = "1.2.0"
# Oldest installed version a release can update in place (release manifest
# min_from): older instances are reinstalled
MIN_UPGRADE_FROM = "1.2.0"

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
# Next to backend/: written by the release build (or by madmin-update
# bootstrap). Without it (a development checkout) the build is "dev".
_MANIFEST = os.path.join(os.path.dirname(_BACKEND_DIR), "manifest.json")
# Installation root: releases/, current, etc/, data/, updater/, state/
INSTALL_ROOT = os.environ.get("MADMIN_ROOT", "/opt/madmin")


@lru_cache
def build_info() -> dict:
    """What this installation runs: version, build (git commit), release id
    and on-disk layout revision (0 = flat /opt/madmin without the updater,
    1 = /opt/madmin/releases/<id> with madmin-update)."""
    try:
        with open(_MANIFEST) as f:
            m = json.load(f)
    except (OSError, ValueError):
        m = {}
    build = str(m.get("build") or "dev")[:40]
    return {
        "version": MADMIN_VERSION,
        "build": build,
        "release_id": f"{MADMIN_VERSION}+{build}",
        "layout": int(m.get("layout") or 0),
    }


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""
    
    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://madmin:madmin@localhost:5432/madmin",
        description="PostgreSQL connection URL"
    )
    
    # Security
    secret_key: str = Field(
        description='Secret key for JWT token signing. Generate with: python -c "import secrets; print(secrets.token_hex(32))"'
    )

    @field_validator('secret_key')
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        # Rejects the placeholders too (.env.example's CHANGE_THIS_TO_A_RANDOM_...
        # is 48 characters long and used to pass): a known key lets anyone
        # forge sessions and read the encrypted settings
        weak = {'CHANGE_THIS_IN_PRODUCTION', '', 'secret', 'changeme', 'password'}
        if v in weak or len(v) < 32 or 'change' in v.lower():
            raise ValueError(
                'SECRET_KEY non sicuro o troppo corto. '
                'Genera un valore con: python -c "import secrets; print(secrets.token_hex(32))"'
            )
        return v
    access_token_expire_minutes: int = Field(
        default=720,  # 12 hours
        description="JWT token expiration in minutes"
    )
    
    # Server
    debug: bool = Field(default=False, description="Enable debug mode")
    allowed_origins: str = Field(
        default="*",
        description="CORS allowed origins (comma-separated or *)"
    )
    
    # Paths
    data_dir: str = Field(
        default="/opt/madmin/data",
        description="Data directory for backups and uploads"
    )
    modules_dir: str = Field(
        default=os.path.join(_BACKEND_DIR, "modules"),
        description="Directory of the modules (shipped with the release)"
    )
    cron_scripts_dir: str = Field(
        default="/opt/madmin/cron-scripts",
        description=(
            "Scripts that scheduled jobs may run. MADMIN never writes here: "
            "scripts are placed by an operator with shell access, which is what "
            "keeps the scheduler from being an arbitrary-command runner."
        )
    )
    
    # Feature flags
    mock_iptables: bool = Field(
        default=False,
        description="Mock iptables commands (for development)"
    )
    
    @property
    def cors_origins(self) -> List[str]:
        """Parse CORS origins from comma-separated string."""
        if self.allowed_origins == "*":
            return ["*"]
        return [origin.strip() for origin in self.allowed_origins.split(",")]
    
    class Config:
        # The installed settings, then a development .env next to backend/
        env_file = (os.path.join(INSTALL_ROOT, "etc", "madmin.env"), ".env")
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.
    Uses LRU cache to avoid re-reading environment on every call.
    """
    return Settings()
