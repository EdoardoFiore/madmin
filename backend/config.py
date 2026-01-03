"""
MADMIN Configuration Module

Loads settings from environment variables with type validation.
Uses Pydantic Settings for robust configuration management.
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List
from functools import lru_cache


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""
    
    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://madmin:madmin@localhost:5432/madmin",
        description="PostgreSQL connection URL"
    )
    
    # Security
    secret_key: str = Field(
        default="CHANGE_THIS_IN_PRODUCTION",
        description="Secret key for JWT token signing"
    )
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
    staging_dir: str = Field(
        default="/opt/madmin/backend/staging",
        description="Directory for development modules"
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
