"""
SQLAlchemy database models for Regression Tracker.

This module defines the database schema for storing test results,
job summaries, and configuration settings.
"""
from datetime import datetime
import enum
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, Enum as SQLEnum, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class TestStatusEnum(str, enum.Enum):
    """Test execution status enum matching existing models.py"""
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


class Release(Base):
    """Tracks releases being monitored."""
    __tablename__ = "releases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False, index=True)  # e.g., "7.0.0.0"
    is_active = Column(Boolean, default=True)  # Whether to poll Jenkins for this release
    jenkins_job_url = Column(String(500))  # Main job URL for downloads
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    modules = relationship("Module", back_populates="release", cascade="all, delete-orphan")
    polling_logs = relationship("JenkinsPollingLog", back_populates="release")

    def __repr__(self):
        return f"<Release(name='{self.name}', is_active={self.is_active})>"


class Module(Base):
    """Modules within a release (business_policy, routing, etc.)"""
    __tablename__ = "modules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    release_id = Column(Integer, ForeignKey("releases.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)  # e.g., "business_policy"
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    release = relationship("Release", back_populates="modules")
    jobs = relationship("Job", back_populates="module", cascade="all, delete-orphan")

    # Composite unique constraint
    __table_args__ = (
        Index('idx_release_module', 'release_id', 'name', unique=True),
    )

    def __repr__(self):
        return f"<Module(name='{self.name}', release_id={self.release_id})>"


class Job(Base):
    """Individual job runs for a module."""
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    module_id = Column(Integer, ForeignKey("modules.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(String(20), nullable=False)  # Jenkins job number (e.g., "123")

    # Summary statistics (denormalized for performance)
    total = Column(Integer, default=0)
    passed = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    skipped = Column(Integer, default=0)
    error = Column(Integer, default=0)
    pass_rate = Column(Float, default=0.0)  # Calculated: (passed/(total-skipped))*100

    # Job metadata
    jenkins_url = Column(String(500))  # Full job URL
    created_at = Column(DateTime, default=datetime.utcnow)
    downloaded_at = Column(DateTime)  # When artifacts were downloaded

    # Relationships
    module = relationship("Module", back_populates="jobs")
    test_results = relationship("TestResult", back_populates="job", cascade="all, delete-orphan")

    # Composite unique constraint and indexes
    __table_args__ = (
        Index('idx_module_job', 'module_id', 'job_id', unique=True),
        Index('idx_job_created', 'created_at'),  # For ordering
    )

    def __repr__(self):
        return f"<Job(job_id='{self.job_id}', module_id={self.module_id}, pass_rate={self.pass_rate:.1f}%)>"


class TestResult(Base):
    """Individual test execution results."""
    __tablename__ = "test_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)

    # Test identification (matching existing TestResult dataclass)
    file_path = Column(String(500), nullable=False)
    class_name = Column(String(200), nullable=False)
    test_name = Column(String(200), nullable=False)

    # Test execution details
    status = Column(SQLEnum(TestStatusEnum), nullable=False, index=True)
    setup_ip = Column(String(50))
    topology = Column(String(100), index=True)
    order_index = Column(Integer, default=0)  # Execution order

    # Rerun tracking
    was_rerun = Column(Boolean, default=False)
    rerun_still_failed = Column(Boolean, default=False)

    # Failure details
    failure_message = Column(Text)  # Can be very long

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    job = relationship("Job", back_populates="test_results")

    # Indexes for efficient queries
    __table_args__ = (
        Index('idx_test_key', 'file_path', 'class_name', 'test_name'),  # For trend queries
        Index('idx_job_status', 'job_id', 'status'),  # For filtering
        Index('idx_topology', 'topology'),  # For grouping
    )

    @property
    def test_key(self) -> str:
        """Unique test identifier (matches existing logic)."""
        return f"{self.file_path}::{self.class_name}::{self.test_name}"

    def __repr__(self):
        return f"<TestResult(test_name='{self.test_name}', status={self.status.value})>"


class AppSettings(Base):
    """Application configuration settings (key-value store)."""
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text)  # JSON-encoded for complex values
    description = Column(String(500))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<AppSettings(key='{self.key}')>"


class JenkinsPollingLog(Base):
    """Logs Jenkins polling attempts and results."""
    __tablename__ = "jenkins_polling_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    release_id = Column(Integer, ForeignKey("releases.id", ondelete="CASCADE"))

    status = Column(String(20))  # 'success', 'failed', 'partial'
    modules_downloaded = Column(Integer, default=0)
    error_message = Column(Text)

    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime)

    # Relationships
    release = relationship("Release", back_populates="polling_logs")

    __table_args__ = (
        Index('idx_polling_started', 'started_at'),
    )

    def __repr__(self):
        return f"<JenkinsPollingLog(release_id={self.release_id}, status='{self.status}', started_at={self.started_at})>"
