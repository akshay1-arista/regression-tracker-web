"""
Pydantic schemas for API request/response validation.

These schemas define the API contract separate from database models
for clean separation of concerns.
"""
from datetime import datetime
from typing import Optional, Dict, List, TypeVar, Generic
from pydantic import BaseModel, Field, HttpUrl, field_validator
from app.models.db_models import TestStatusEnum

# Type variable for pagination
T = TypeVar('T')


# Response Schemas

class BugSchema(BaseModel):
    """Schema for bug metadata in API responses."""
    defect_id: str
    bug_type: str  # "VLEI" or "VLENG"
    url: str
    status: Optional[str] = None
    summary: Optional[str] = None
    priority: Optional[str] = None
    assignee: Optional[str] = None
    component: Optional[str] = None

    class Config:
        from_attributes = True


class TestResultSchema(BaseModel):
    """Schema for test result response."""
    test_key: str
    test_name: str
    class_name: str
    file_path: str
    status: TestStatusEnum
    setup_ip: Optional[str] = None
    jenkins_topology: Optional[str] = None          # Execution topology from JUnit XML
    topology_metadata: Optional[str] = None         # Design topology from metadata CSV
    priority: Optional[str] = None  # P0, P1, P2, P3, or None
    testcase_module: Optional[str] = None           # Module derived from file path (e.g., "business_policy", "routing")
    was_rerun: bool = False
    rerun_still_failed: bool = False
    failure_message: Optional[str] = None
    order_index: int = 0
    bugs: List[BugSchema] = []  # Associated bugs (VLEI/VLENG)

    class Config:
        from_attributes = True  # Pydantic v2


class JobSummarySchema(BaseModel):
    """Schema for job summary response."""
    job_id: str
    total: int
    passed: int
    failed: int  # Includes both FAILED and ERROR statuses
    skipped: int
    pass_rate: float
    jenkins_url: Optional[str] = None
    created_at: datetime
    downloaded_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TestTrendSchema(BaseModel):
    """Schema for test trend across multiple jobs."""
    test_key: str
    file_path: str
    class_name: str
    test_name: str
    priority: Optional[str] = None  # P0, P1, P2, P3, or None
    topology_metadata: Optional[str] = None  # Design topology from metadata CSV
    results_by_job: Dict[str, str]  # job_id -> status
    rerun_info_by_job: Dict[str, Dict[str, bool]]  # job_id -> {was_rerun, rerun_still_failed}
    job_modules: Dict[str, str]  # job_id -> Jenkins module name (for correct job URLs)
    parent_job_ids: Dict[str, str]  # job_id -> parent_job_id (for frontend filtering)
    is_flaky: bool
    is_regression: bool
    is_always_failing: bool
    is_always_passing: bool
    is_new_failure: bool
    latest_status: str


class ModuleSummarySchema(BaseModel):
    """Schema for module summary."""
    name: str
    total_jobs: int
    last_job_id: Optional[str] = None
    last_job_pass_rate: Optional[float] = None


class ReleaseSummarySchema(BaseModel):
    """Schema for release summary."""
    name: str
    is_active: bool
    last_updated: datetime
    total_modules: int


# Pagination Schemas

class PaginationMetadata(BaseModel):
    """Pagination metadata for list responses."""
    total: int = Field(..., description="Total number of items")
    skip: int = Field(..., description="Number of items skipped")
    limit: int = Field(..., description="Maximum items per page")
    has_next: bool = Field(..., description="Whether there are more items")
    has_previous: bool = Field(..., description="Whether there are previous items")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response wrapper."""
    items: List[T] = Field(..., description="List of items for current page")
    metadata: PaginationMetadata = Field(..., description="Pagination metadata")


# Request Schemas

class JenkinsDownloadRequest(BaseModel):
    """Request schema for manual Jenkins download."""
    release: str = Field(..., min_length=1, max_length=50, description="Release name")
    job_url: HttpUrl = Field(..., description="Main Jenkins job URL (must be valid HTTP/HTTPS URL)")
    skip_existing: bool = Field(False, description="Skip download if files already exist")


class PollingToggleRequest(BaseModel):
    """Request schema for toggling polling."""
    enabled: bool


class PollingIntervalRequest(BaseModel):
    """Request schema for updating polling interval."""
    interval_minutes: int = Field(..., ge=1, le=1440, description="Polling interval in minutes (1-1440)")


class SettingUpdateRequest(BaseModel):
    """Request schema for updating a setting."""
    value: str = Field(..., description="Setting value (JSON-encoded for complex types)")


class ReleaseCreateRequest(BaseModel):
    """Request schema for creating a new release."""
    name: str = Field(..., min_length=1, max_length=50, pattern=r'^[0-9.]+$',
                     description="Release version (e.g., '7.0.0.0', numbers and dots only)")
    jenkins_job_url: HttpUrl = Field(..., description="Jenkins job URL (must be valid HTTP/HTTPS URL)")
    is_active: bool = Field(True, description="Whether to actively poll this release")


# Dashboard Response Schemas

class ReleaseResponse(BaseModel):
    """Release information response."""
    name: str
    is_active: bool
    jenkins_job_url: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ModuleResponse(BaseModel):
    """Module information response."""
    name: str
    release: str
    created_at: datetime

    class Config:
        from_attributes = True


class ModuleBreakdownSchema(BaseModel):
    """Per-module statistics in All Modules view (path-based modules)."""
    module_name: str
    total: int
    passed: int
    failed: int  # Includes both FAILED and ERROR statuses
    skipped: int
    pass_rate: float


class DashboardSummaryResponse(BaseModel):
    """Complete dashboard summary response."""
    release: str
    module: str
    summary: Dict
    recent_jobs: List[Dict]
    pass_rate_history: List[Dict]
    module_breakdown: Optional[List[ModuleBreakdownSchema]] = None  # For "All Modules" view


class JobDetailsResponse(BaseModel):
    """Complete job details response."""
    job: JobSummarySchema
    statistics: Dict
    tests: List[TestResultSchema]


class PollingStatusResponse(BaseModel):
    """Polling status response."""
    enabled: bool
    interval_minutes: int
    last_run: Optional[Dict] = None
    next_run: Optional[datetime] = None


# Request/Query Parameter Schemas

class PriorityFilterParams(BaseModel):
    """
    Query parameter model for priority filtering.

    Validates priority values and provides a list of valid priorities.
    Use in route handlers as a dependency to validate priority query parameters.
    """
    priorities: Optional[List[str]] = Field(
        None,
        description="Comma-separated list of priorities to filter by (P0, P1, P2, P3, UNKNOWN)"
    )

    @field_validator('priorities', mode='before')
    @classmethod
    def parse_priorities(cls, v):
        """Parse comma-separated string into list of priorities."""
        if v is None:
            return None
        if isinstance(v, str):
            # Split by comma and strip whitespace
            return [p.strip().upper() for p in v.split(',') if p.strip()]
        return v

    @field_validator('priorities')
    @classmethod
    def validate_priorities(cls, v):
        """Validate that all priorities are valid."""
        if v is None:
            return None

        valid_priorities = {'P0', 'P1', 'P2', 'P3', 'UNKNOWN'}
        invalid = [p for p in v if p not in valid_priorities]

        if invalid:
            raise ValueError(
                f"Invalid priorities: {', '.join(invalid)}. "
                f"Valid values: {', '.join(sorted(valid_priorities))}"
            )

        return v


# Error Clustering Schemas

class ErrorSignatureSchema(BaseModel):
    """Schema for error signature in clustering response."""
    error_type: str = Field(..., description="Type of error (AssertionError, IndexError, etc.)")
    file_path: Optional[str] = Field(None, description="Source file path where error occurred")
    line_number: Optional[int] = Field(None, description="Line number where error occurred")
    normalized_message: str = Field(..., description="Error message with variables replaced by placeholders")
    fingerprint: str = Field(..., description="Hash fingerprint for exact matching")

    class Config:
        from_attributes = True


class ErrorClusterSchema(BaseModel):
    """Schema for a cluster of similar test failures."""
    signature: ErrorSignatureSchema = Field(..., description="Common error signature for this cluster")
    count: int = Field(..., description="Number of tests in this cluster")
    affected_tests: List[str] = Field(..., description="List of test keys in this cluster")
    affected_topologies: List[str] = Field(default_factory=list, description="Set of topologies affected")
    affected_priorities: List[str] = Field(default_factory=list, description="Set of priorities affected")
    sample_message: str = Field(..., description="Full original error message for reference")
    match_type: str = Field(..., description="Matching strategy used: 'exact' or 'fuzzy'")
    test_results: List[TestResultSchema] = Field(..., description="Full test result details")

    class Config:
        from_attributes = True


class ClusterSummarySchema(BaseModel):
    """Schema for cluster summary statistics."""
    total_failures: int = Field(..., description="Total number of failed tests analyzed")
    unique_clusters: int = Field(..., description="Number of distinct error patterns found")
    largest_cluster: int = Field(..., description="Size of the largest cluster")
    unclustered: int = Field(..., description="Number of failures in singleton clusters")

    class Config:
        from_attributes = True


class ClusterResponseSchema(BaseModel):
    """Complete error clustering response."""
    clusters: List[ErrorClusterSchema] = Field(..., description="List of error clusters")
    summary: ClusterSummarySchema = Field(..., description="Summary statistics")

    class Config:
        from_attributes = True
