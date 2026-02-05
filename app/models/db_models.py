"""
SQLAlchemy database models for Regression Tracker.

This module defines the database schema for storing test results,
job summaries, and configuration settings.
"""
from datetime import datetime, timezone
import enum
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, Enum as SQLEnum, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


def utcnow() -> datetime:
    """Return current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


class TestStatusEnum(str, enum.Enum):
    """Test execution status enum matching existing models.py

    Note: ERROR is kept for parser compatibility (can accept from Jenkins XML),
    but all ERROR statuses are automatically converted to FAILED on import.
    """
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"  # Kept for parser compatibility, converted to FAILED on import


class Release(Base):
    """Tracks releases being monitored."""
    __tablename__ = "releases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False, index=True)  # e.g., "7.0.0.0"
    is_active = Column(Boolean, default=True)  # Whether to poll Jenkins for this release
    jenkins_job_url = Column(String(2000))  # Main job URL for downloads (increased for long URLs)
    last_processed_build = Column(Integer, default=0)  # Last main job build number processed
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

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
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

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
    parent_job_id = Column(String(20))  # Parent Jenkins job that spawned this module job

    # Summary statistics (denormalized for performance)
    total = Column(Integer, default=0)
    passed = Column(Integer, default=0)
    failed = Column(Integer, default=0)  # Includes both FAILED and ERROR statuses
    skipped = Column(Integer, default=0)
    pass_rate = Column(Float, default=0.0)  # Calculated: (passed/(total-skipped))*100

    # Job metadata
    jenkins_url = Column(String(2000))  # Full job URL (increased for long URLs)
    version = Column(String(50))  # Version extracted from job title (e.g., "7.0.0.0")
    created_at = Column(DateTime, default=utcnow)
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
    file_path = Column(Text, nullable=False)  # Unbounded for potentially long test file paths
    class_name = Column(String(200), nullable=False)
    test_name = Column(String(200), nullable=False)

    # Test execution details
    status = Column(SQLEnum(TestStatusEnum), nullable=False, index=True)
    setup_ip = Column(String(50))
    jenkins_topology = Column(String(100), index=True)  # Execution topology from JUnit XML
    order_index = Column(Integer, default=0)  # Execution order

    # Rerun tracking
    was_rerun = Column(Boolean, default=False)
    rerun_still_failed = Column(Boolean, default=False)

    # Failure details
    failure_message = Column(Text)  # Can be very long

    # Metadata fields (denormalized from TestcaseMetadata for fast filtering)
    priority = Column(String(5), index=True)  # P0, P1, P2, P3, or NULL
    topology_metadata = Column(String(100), index=True)  # Design topology from metadata CSV

    # Module derived from file path (for correct categorization regardless of which Jenkins job ran it)
    testcase_module = Column(String(100), index=True)  # e.g., "business_policy", "routing"

    # Timestamps
    created_at = Column(DateTime, default=utcnow)

    # Relationships
    job = relationship("Job", back_populates="test_results")

    # Indexes for efficient queries
    __table_args__ = (
        Index('idx_test_key', 'file_path', 'class_name', 'test_name'),  # For trend queries
        Index('idx_job_status', 'job_id', 'status'),  # For filtering
        Index('idx_job_topology', 'job_id', 'jenkins_topology'),  # For filtering by job and execution topology
        Index('idx_topology', 'jenkins_topology'),  # For grouping by execution topology
        Index('idx_topology_metadata', 'topology_metadata'),  # For grouping by design topology (NEW)
        Index('idx_priority', 'priority'),  # For priority filtering
        Index('idx_test_name_priority', 'test_name', 'priority'),  # Compound index for matching
    )

    @property
    def test_key(self) -> str:
        """Unique test identifier (matches existing logic)."""
        return f"{self.file_path}::{self.class_name}::{self.test_name}"

    def __repr__(self):
        return f"<TestResult(test_name='{self.test_name}', status={self.status.value})>"


class TestcaseMetadata(Base):
    """Testcase metadata from CSV imports (hapy_automated.csv, dataplane_test_topologies.csv)."""
    __tablename__ = "testcase_metadata"

    id = Column(Integer, primary_key=True, autoincrement=True)
    testcase_name = Column(String(200), nullable=False)  # Index defined in __table_args__
    test_case_id = Column(String(50))  # Index defined in __table_args__
    priority = Column(String(5))  # P0, P1, P2, P3 - Index defined in __table_args__
    testrail_id = Column(String(20))  # Index defined in __table_args__
    component = Column(String(100))  # e.g., "DataPlane"
    automation_status = Column(String(50))  # e.g., "Hapy Automated"

    # NEW FIELDS FROM dataplane_test_topologies.csv
    module = Column(String(100))              # e.g., "business_policy", "routing"
    test_state = Column(String(50))           # e.g., "PROD", "STAGING"
    test_class_name = Column(String(200))     # e.g., "TestBackhaulToHub"
    test_path = Column(Text)                  # Full file path from CSV
    topology = Column(String(100))            # e.g., "5-site", "3-site-ipv6"

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index('idx_testcase_name', 'testcase_name', unique=True),
        Index('idx_priority_meta', 'priority'),
        Index('idx_test_case_id', 'test_case_id'),
        Index('idx_testrail_id', 'testrail_id'),
        Index('idx_module_meta', 'module'),                    # NEW
        Index('idx_topology_meta', 'topology'),                # NEW
        Index('idx_test_state_meta', 'test_state'),            # NEW
    )

    def __repr__(self):
        return f"<TestcaseMetadata(testcase_name='{self.testcase_name}', priority='{self.priority}', topology='{self.topology}')>"


class AppSettings(Base):
    """Application configuration settings (key-value store)."""
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text)  # JSON-encoded for complex values
    description = Column(String(500))
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

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


class BugMetadata(Base):
    """Bug tracking metadata from Jenkins VLEI/VLENG JSON."""
    __tablename__ = "bug_metadata"

    id = Column(Integer, primary_key=True, autoincrement=True)
    defect_id = Column(String(50), nullable=False, unique=True)
    bug_type = Column(String(10), nullable=False)  # VLEI or VLENG
    url = Column(String(500), nullable=False)
    status = Column(String(50))
    summary = Column(Text)
    priority = Column(String(20))
    assignee = Column(String(100))
    component = Column(String(100))
    resolution = Column(String(50))
    affected_versions = Column(String(200))
    labels = Column(Text)  # JSON string
    is_active = Column(Boolean, default=True, nullable=False)  # Whether bug is in latest Jenkins JSON
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    mappings = relationship("BugTestcaseMapping", back_populates="bug",
                           cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_defect_id', 'defect_id', unique=True),
        Index('idx_bug_type', 'bug_type'),
        Index('idx_status', 'status'),
        Index('idx_is_active', 'is_active'),
    )

    def __repr__(self):
        return f"<BugMetadata(defect_id='{self.defect_id}', bug_type='{self.bug_type}', status='{self.status}')>"


class BugTestcaseMapping(Base):
    """Many-to-many mapping between bugs and test cases."""
    __tablename__ = "bug_testcase_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    bug_id = Column(Integer, ForeignKey('bug_metadata.id', ondelete='CASCADE'),
                   nullable=False)
    case_id = Column(String(50), nullable=False)  # Matches test_case_id or testrail_id
    created_at = Column(DateTime, default=utcnow)

    # Relationships
    bug = relationship("BugMetadata", back_populates="mappings")

    __table_args__ = (
        Index('idx_case_id', 'case_id'),
        Index('idx_bug_id', 'bug_id'),
        Index('idx_bug_case_unique', 'bug_id', 'case_id', unique=True),
    )

    def __repr__(self):
        return f"<BugTestcaseMapping(bug_id={self.bug_id}, case_id='{self.case_id}')>"


class MetadataSyncLog(Base):
    """Logs metadata synchronization attempts and results."""
    __tablename__ = "metadata_sync_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Sync metadata
    status = Column(String(20), nullable=False)  # 'success', 'failed', 'partial'
    sync_type = Column(String(20))  # 'scheduled', 'manual'
    git_commit_hash = Column(String(40))  # Git commit SHA synced from

    # Statistics
    tests_discovered = Column(Integer, default=0)
    tests_added = Column(Integer, default=0)
    tests_updated = Column(Integer, default=0)
    tests_removed = Column(Integer, default=0)  # Soft delete count

    # Error tracking
    error_message = Column(Text)
    error_details = Column(Text)  # JSON-encoded details for debugging

    # Timestamps
    started_at = Column(DateTime, nullable=False, default=utcnow)
    completed_at = Column(DateTime)

    __table_args__ = (
        Index('idx_sync_started', 'started_at'),
        Index('idx_sync_status', 'status'),
    )

    def __repr__(self):
        return f"<MetadataSyncLog(id={self.id}, status='{self.status}', started_at={self.started_at})>"


class TestcaseMetadataChange(Base):
    """Audit trail for testcase metadata changes from Git sync."""
    __tablename__ = "testcase_metadata_changes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sync_log_id = Column(Integer, ForeignKey('metadata_sync_logs.id', ondelete='CASCADE'))

    testcase_name = Column(String(200), nullable=False)
    change_type = Column(String(20), nullable=False)  # 'added', 'updated', 'removed'

    # Before/after snapshots (JSON-encoded)
    old_values = Column(Text)  # JSON: {field: old_value}
    new_values = Column(Text)  # JSON: {field: new_value}

    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (
        Index('idx_change_sync_log', 'sync_log_id'),
        Index('idx_change_testcase', 'testcase_name'),
    )

    def __repr__(self):
        return f"<TestcaseMetadataChange(id={self.id}, testcase_name='{self.testcase_name}', change_type='{self.change_type}')>"
