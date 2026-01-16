"""
FastAPI main application for Regression Tracker Web.

Provides REST API endpoints for accessing test results, trends, and job data.
"""
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from fastapi_cache.decorator import cache

from app.config import get_settings
from app.database import engine
from app.models.db_models import Base
from app.tasks.scheduler import start_scheduler, stop_scheduler
from sqlalchemy import text

# Configure logging from settings
settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper()),
    format=settings.LOG_FORMAT,
    handlers=[
        logging.StreamHandler(),  # Console output
    ]
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI application.
    Handles startup and shutdown events.
    """
    # Startup
    logger.info("Starting Regression Tracker Web API")
    settings = get_settings()
    logger.info(f"Database: {settings.DATABASE_URL}")
    logger.info(f"Auto-update enabled: {settings.AUTO_UPDATE_ENABLED}")

    # Create tables if they don't exist (for development)
    # In production, use Alembic migrations instead
    Base.metadata.create_all(bind=engine)

    # Initialize caching
    if settings.CACHE_ENABLED:
        if settings.REDIS_URL:
            # Use Redis if URL provided
            try:
                from fastapi_cache.backends.redis import RedisBackend
                from redis import asyncio as aioredis
                redis = aioredis.from_url(settings.REDIS_URL, encoding="utf8", decode_responses=True)
                FastAPICache.init(RedisBackend(redis), prefix="fastapi-cache")
                logger.info(f"Cache initialized with Redis: {settings.REDIS_URL}")
            except Exception as e:
                logger.warning(f"Failed to connect to Redis, falling back to in-memory cache: {e}")
                FastAPICache.init(InMemoryBackend(), prefix="fastapi-cache")
                logger.info("Cache initialized with in-memory backend")
        else:
            # Use in-memory cache
            FastAPICache.init(InMemoryBackend(), prefix="fastapi-cache")
            logger.info("Cache initialized with in-memory backend")
    else:
        logger.info("Caching disabled")

    # Start background scheduler for Jenkins polling
    try:
        start_scheduler()
        logger.info("Background scheduler started successfully")
    except Exception as e:
        logger.error(f"Failed to start background scheduler: {e}", exc_info=True)

    yield

    # Shutdown
    logger.info("Shutting down Regression Tracker Web API")

    # Stop background scheduler
    try:
        stop_scheduler()
        logger.info("Background scheduler stopped")
    except Exception as e:
        logger.error(f"Error stopping scheduler: {e}", exc_info=True)


# Create FastAPI application
app = FastAPI(
    title="Regression Tracker Web API",
    description="""
    REST API for tracking regression test results across Jenkins jobs.

    ## Authentication

    API key authentication can be enabled via environment variables:
    - Set `API_KEY` to require authentication for all endpoints
    - Set `ADMIN_API_KEY` for admin-level operations
    - Provide the key in the `X-API-Key` request header

    When authentication is disabled (no API keys set), all endpoints are publicly accessible.
    """,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# Mount static files directory FIRST (before any middleware or routers)
# This is required for Jinja2 templates to use url_for('static', ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
static_dir = os.path.join(BASE_DIR, "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Configure rate limiting
if settings.RATE_LIMIT_ENABLED:
    # Create limiter with default limits
    rate_limit_string = f"{settings.RATE_LIMIT_PER_MINUTE}/minute"
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=[rate_limit_string]
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    logger.info(f"Rate limiting enabled: {rate_limit_string}")
else:
    # Create limiter without limits (disabled)
    limiter = Limiter(key_func=get_remote_address, enabled=False)
    app.state.limiter = limiter
    logger.info("Rate limiting disabled")

# Configure CORS with specific allowed origins
allowed_origins = settings.ALLOWED_ORIGINS.split(",") if settings.ALLOWED_ORIGINS else []
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,  # Specific origins only
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],  # Specific methods
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],  # Specific headers
)

# Add SlowAPI middleware for rate limiting
if settings.RATE_LIMIT_ENABLED:
    app.add_middleware(SlowAPIMiddleware)


# Global exception handlers
@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    """Handle SQLAlchemy database errors."""
    logger.error(f"Database error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Database error",
            "detail": "An error occurred while accessing the database"
        }
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    """Handle ValueError exceptions (often from invalid input)."""
    logger.warning(f"Value error: {exc}")
    return JSONResponse(
        status_code=400,
        content={
            "error": "Invalid input",
            "detail": str(exc)
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions."""
    logger.exception(f"Unexpected error: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": "An unexpected error occurred"
        }
    )


# Health check endpoints
@app.get("/health", tags=["System"])
async def health_check():
    """
    Basic health check endpoint - returns minimal status.

    Returns:
        Status information about the application
    """
    return {
        "status": "healthy",
        "version": "1.0.0"
    }


@app.get("/health/detailed", tags=["System"])
async def detailed_health_check():
    """
    Detailed health check endpoint for monitoring systems.

    Checks:
    - Application status
    - Database connectivity
    - Background scheduler status
    - Cache status

    Returns:
        Comprehensive health status
    """
    from app.database import SessionLocal
    from app.tasks.scheduler import scheduler
    from datetime import datetime, timezone

    health_status = {
        "status": "healthy",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {}
    }

    # Check database connectivity
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        health_status["checks"]["database"] = {
            "status": "healthy",
            "message": "Database connection successful"
        }
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["checks"]["database"] = {
            "status": "unhealthy",
            "message": f"Database connection failed: {str(e)}"
        }
        logger.error(f"Database health check failed: {e}")

    # Check scheduler status
    try:
        if settings.AUTO_UPDATE_ENABLED:
            is_running = scheduler is not None and scheduler.running
            health_status["checks"]["scheduler"] = {
                "status": "healthy" if is_running else "degraded",
                "message": f"Scheduler is {'running' if is_running else 'not running'}",
                "running": is_running
            }
            if not is_running:
                health_status["status"] = "degraded"
        else:
            health_status["checks"]["scheduler"] = {
                "status": "disabled",
                "message": "Auto-update disabled in configuration"
            }
    except Exception as e:
        health_status["status"] = "degraded"
        health_status["checks"]["scheduler"] = {
            "status": "error",
            "message": f"Scheduler check failed: {str(e)}"
        }
        logger.error(f"Scheduler health check failed: {e}")

    # Check cache status
    try:
        if settings.CACHE_ENABLED:
            health_status["checks"]["cache"] = {
                "status": "healthy",
                "message": "Cache is enabled",
                "backend": "redis" if settings.REDIS_URL else "in-memory"
            }
        else:
            health_status["checks"]["cache"] = {
                "status": "disabled",
                "message": "Caching disabled in configuration"
            }
    except Exception as e:
        health_status["checks"]["cache"] = {
            "status": "error",
            "message": f"Cache check failed: {str(e)}"
        }
        logger.warning(f"Cache health check failed: {e}")

    # Set overall status based on checks
    unhealthy_checks = [
        check for check in health_status["checks"].values()
        if check.get("status") == "unhealthy"
    ]
    if unhealthy_checks:
        health_status["status"] = "unhealthy"

    return health_status


@app.get("/health/live", tags=["System"])
async def liveness_probe():
    """
    Kubernetes liveness probe endpoint.

    Returns 200 if the application is running, 503 if not.
    Used by Kubernetes to determine if pod should be restarted.
    """
    return {"status": "alive"}


@app.get("/health/ready", tags=["System"])
async def readiness_probe():
    """
    Kubernetes readiness probe endpoint.

    Returns 200 if ready to serve traffic, 503 if not.
    Used by Kubernetes to determine if pod should receive traffic.
    """
    from app.database import SessionLocal

    try:
        # Check database is accessible
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as e:
        logger.error(f"Readiness probe failed: {e}")
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "reason": "database unavailable"}
        )


@app.get("/api/v1", tags=["System"])
async def api_root():
    """
    API root endpoint.

    Returns:
        Welcome message with API documentation link
    """
    return {
        "message": "Regression Tracker Web API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": {
            "basic": "/health",
            "detailed": "/health/detailed",
            "liveness": "/health/live",
            "readiness": "/health/ready"
        }
    }


# Import and register routers with API versioning
from app.routers import dashboard, trends, jobs, views, jenkins, admin

# v1 API endpoints (current)
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["Dashboard v1"])
app.include_router(trends.router, prefix="/api/v1/trends", tags=["Trends v1"])
app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["Jobs v1"])
app.include_router(jenkins.router, prefix="/api/v1/jenkins", tags=["Jenkins v1"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin v1"])

# Maintain backward compatibility with /api/* (alias to v1)
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"], include_in_schema=False)
app.include_router(trends.router, prefix="/api/trends", tags=["Trends"], include_in_schema=False)
app.include_router(jobs.router, prefix="/api/jobs", tags=["Jobs"], include_in_schema=False)
app.include_router(jenkins.router, prefix="/api/jenkins", tags=["Jenkins"], include_in_schema=False)
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"], include_in_schema=False)

# HTML view routes (no prefix - handles /, /trends, /jobs, /admin)
app.include_router(views.router, tags=["Views"], include_in_schema=False)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info"
    )
