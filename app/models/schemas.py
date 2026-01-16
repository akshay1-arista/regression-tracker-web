"""
Pydantic schemas for API request/response validation.

These schemas define the API contract separate from database models
for clean separation of concerns.
"""
from datetime import datetime
from typing import Optional, Dict, List
from pydantic import BaseModel, Field, HttpUrl, field_validator
from app.models.db_models import TestStatusEnum


# Response Schemas

class TestResultSchema(BaseModel):
    """Schema for test result response."""
    test_key: str
    test_name: str
    class_name: str
    file_path: str
    status: TestStatusEnum
    setup_ip: Optional[str] = None
    topology: Optional[str] = None
    was_rerun: bool = False
    rerun_still_failed: bool = False
    failure_message: Optional[str] = None
    order_index: int = 0

    class Config:
        from_attributes = True  # Pydantic v2


class JobSummarySchema(BaseModel):
    """Schema for job summary response."""
    job_id: str
    total: int
    passed: int
    failed: int
    skipped: int
    error: int
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
    results_by_job: Dict[str, str]  # job_id -> status
    rerun_info_by_job: Dict[str, Dict[str, bool]]  # job_id -> {was_rerun, rerun_still_failed}
    is_flaky: bool
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


class DashboardSummaryResponse(BaseModel):
    """Complete dashboard summary response."""
    release: str
    module: str
    summary: Dict
    recent_jobs: List[Dict]
    pass_rate_history: List[Dict]


class JobDetailsResponse(BaseModel):
    """Complete job details response."""
    job: JobSummarySchema
    statistics: Dict[str, int]
    tests: List[TestResultSchema]


class PollingStatusResponse(BaseModel):
    """Polling status response."""
    enabled: bool
    interval_minutes: int
    last_run: Optional[Dict] = None
    next_run: Optional[datetime] = None
