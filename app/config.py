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
    JENKINS_BUILD_QUERY_LIMIT: int = 100  # Max number of recent builds to fetch per API query
    JENKINS_VERIFY_SSL: bool = True  # Verify SSL certificates for Jenkins connections

    # Bug Tracking
    JENKINS_BUG_DATA_URL: str = "https://jenkins2.vdev.sjc.aristanetworks.com/job/jira_centralize_repo/lastSuccessfulBuild/artifact/vlei_vleng_dict.json"

    # Polling
    AUTO_UPDATE_ENABLED: bool = True
    POLLING_INTERVAL_HOURS: float = 12.0  # Default: 12 hours (can be fractional, e.g. 0.5 = 30 min)

    # Logs
    LOGS_BASE_PATH: str = "./logs"
    CLEANUP_ARTIFACTS_AFTER_IMPORT: bool = True  # Delete artifacts after importing to database to save disk space

    # Application
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # CORS
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:5173,http://localhost:8080"

    # Security
    API_KEY: str = ""  # Optional API key for authentication
    ADMIN_API_KEY: str = ""  # Optional admin API key for sensitive operations
    ADMIN_PIN_HASH: str = ""  # SHA-256 hash of admin PIN for admin page authentication

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PER_MINUTE: int = 100

    # Caching
    CACHE_ENABLED: bool = True
    CACHE_TTL_SECONDS: int = 300  # 5 minutes default TTL
    REDIS_URL: str = ""  # If empty, uses in-memory cache

    # Git Repository Configuration
    GIT_REPO_URL: str = ""  # e.g., git@github.com:velocloud-sdwan/velocloud.src.git
    GIT_REPO_LOCAL_PATH: str = "./data/git_repos/velocloud_src"
    GIT_REPO_BRANCH: str = "master"
    GIT_REPO_SSH_KEY_PATH: str = ""  # Optional, uses system default if empty
    GIT_REPO_HTTPS_TOKEN: str = ""  # Alternative to SSH (not recommended)
    GIT_SSH_STRICT_HOST_KEY_CHECKING: bool = True  # Recommended for security

    # Test Discovery Configuration
    TEST_DISCOVERY_BASE_PATH: str = "hapy/data_plane/tests"
    TEST_DISCOVERY_STAGING_CONFIG: str = "hapy/data_plane/framework/staging/dp_staging.ini"

    # Metadata Sync Scheduling
    METADATA_SYNC_ENABLED: bool = False
    METADATA_SYNC_INTERVAL_HOURS: float = 24.0
    METADATA_SYNC_ON_STARTUP: bool = False

    # Metadata Sync Failure Thresholds
    METADATA_SYNC_MAX_FILE_FAILURE_RATE: float = 0.10  # 10% max failure rate for files
    METADATA_SYNC_MIN_FILE_FAILURES_TO_ABORT: int = 5  # Minimum failed files to trigger abort
    METADATA_SYNC_MAX_BATCH_FAILURE_RATE: float = 0.10  # 10% max failure rate for batches
    METADATA_SYNC_MIN_BATCH_FAILURES_TO_ABORT: int = 2  # Minimum failed batches to trigger abort

    @field_validator('GIT_REPO_URL')
    @classmethod
    def validate_git_url(cls, v: str) -> str:
        """Validate Git URL format (SSH or HTTPS)."""
        if v and not (v.startswith('git@') or v.startswith('https://')):
            raise ValueError('Git URL must start with git@ (SSH) or https:// (HTTPS)')
        return v

    @field_validator('GIT_REPO_LOCAL_PATH')
    @classmethod
    def validate_git_path(cls, v: str) -> str:
        """Prevent path traversal attacks."""
        if '..' in v:
            raise ValueError('Path traversal not allowed in GIT_REPO_LOCAL_PATH')
        return v

    # Model configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra='ignore'  # Allow extra fields in .env without validation errors
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
