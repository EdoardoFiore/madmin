"""
MADMIN Configuration Module

Loads settings from environment variables with type validation.
Uses Pydantic Settings for robust configuration management.
"""
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator
from typing import List
from functools import lru_cache

# Versione MADMIN (usata per export/import config cross-versione)
MADMIN_VERSION = "1.0.0"


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
        weak = {'CHANGE_THIS_IN_PRODUCTION', '', 'secret', 'changeme', 'password'}
        if v in weak or len(v) < 32:
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
        default="/opt/madmin/backend/modules",
        description="Directory for installed modules"
    )
    
    # Feature flags
    mock_iptables: bool = Field(
        default=False,
        description="Mock firewall commands (iptables/nftables) for development"
    )
    firewall_backend: str = Field(
        default="nftables",
        description="Firewall backend: 'nftables' (default) or 'iptables' (legacy)"
    )
    
    @property
    def cors_origins(self) -> List[str]:
        """Parse CORS origins from comma-separated string."""
        if self.allowed_origins == "*":
            return ["*"]
        return [origin.strip() for origin in self.allowed_origins.split(",")]
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.
    Uses LRU cache to avoid re-reading environment on every call.
    """
    return Settings()
