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

# Create SQLAlchemy engine
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
    echo=settings.DEBUG  # Log SQL queries in debug mode
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency for database sessions.

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
