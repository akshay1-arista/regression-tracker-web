"""
FastAPI main application for Regression Tracker Web.

Provides REST API endpoints for accessing test results, trends, and job data.
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.database import engine
from app.models.db_models import Base

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
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

    yield

    # Shutdown
    logger.info("Shutting down Regression Tracker Web API")


# Create FastAPI application
app = FastAPI(
    title="Regression Tracker Web API",
    description="REST API for tracking regression test results across Jenkins jobs",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configure CORS
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify allowed origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


# Health check endpoint
@app.get("/health", tags=["System"])
async def health_check():
    """
    Health check endpoint.

    Returns:
        Status information about the application
    """
    return {
        "status": "healthy",
        "version": "1.0.0",
        "database": settings.DATABASE_URL.split("///")[0] + "///"  # Hide path
    }


@app.get("/", tags=["System"])
async def root():
    """
    Root endpoint.

    Returns:
        Welcome message with API documentation link
    """
    return {
        "message": "Regression Tracker Web API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health"
    }


# Import and register routers
from app.routers import dashboard, trends, jobs

app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(trends.router, prefix="/api/trends", tags=["Trends"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["Jobs"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info"
    )
