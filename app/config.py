"""
Application configuration using Pydantic Settings.

Loads configuration from environment variables with .env file support.
"""
from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    DATABASE_URL: str = "sqlite:///./data/regression_tracker.db"

    @field_validator('DATABASE_URL')
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Validate DATABASE_URL has an allowed scheme to prevent injection."""
        allowed_schemes = ('sqlite:///', 'postgresql://', 'mysql://', 'mysql+pymysql://')
        if not v.startswith(allowed_schemes):
            raise ValueError(
                f'Invalid database URL scheme. Allowed schemes: {", ".join(allowed_schemes)}'
            )
        return v

    # Jenkins
    JENKINS_URL: str = ""
    JENKINS_USER: str = ""
    JENKINS_API_TOKEN: str = ""

    # Polling
    AUTO_UPDATE_ENABLED: bool = True
    POLLING_INTERVAL_MINUTES: int = 15

    # Logs
    LOGS_BASE_PATH: str = "./logs"

    # Application
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Model configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Uses lru_cache to ensure settings are loaded only once.

    Returns:
        Settings instance
    """
    return Settings()
