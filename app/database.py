"""
Database session management and configuration.

This module provides SQLAlchemy engine, session factory, and
dependency injection for FastAPI endpoints.
"""
from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.config import get_settings

settings = get_settings()

# Configure connection pooling for production databases
pool_config = {}
if "postgresql" in settings.DATABASE_URL or "mysql" in settings.DATABASE_URL:
    # Production database pooling configuration
    pool_config = {
        'pool_size': 10,              # Number of connections to maintain
        'max_overflow': 20,            # Maximum number of connections beyond pool_size
        'pool_pre_ping': True,         # Verify connections before using them
        'pool_recycle': 3600,          # Recycle connections after 1 hour
    }
elif "sqlite" in settings.DATABASE_URL:
    # SQLite doesn't benefit from pooling but needs thread safety
    pool_config = {
        'connect_args': {"check_same_thread": False}
    }

# Create SQLAlchemy engine
engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,  # Log SQL queries in debug mode
    **pool_config
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency for database sessions with automatic transaction management.

    Features:
    - Automatic commit on successful request
    - Automatic rollback on exceptions
    - Ensures session is properly closed

    Usage:
        @router.get("/items/")
        def read_items(db: Session = Depends(get_db)):
            return db.query(Item).all()

    Yields:
        Database session
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()  # Auto-rollback on error
        raise
    finally:
        db.close()


@contextmanager
def get_db_context():
    """
    Context manager for database sessions in background tasks.

    Usage:
        with get_db_context() as db:
            db.add(item)
            db.commit()

    Yields:
        Database session
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    """
    Initialize database tables.
    Creates all tables defined in models.

    Note: In production, use Alembic migrations instead.
    """
    from app.models.db_models import Base
    Base.metadata.create_all(bind=engine)


def drop_db():
    """
    Drop all database tables.

    Warning: This will delete all data!
    Only use in development/testing.
    """
    from app.models.db_models import Base
    Base.metadata.drop_all(bind=engine)
