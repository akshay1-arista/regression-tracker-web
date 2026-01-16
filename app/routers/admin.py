"""
Admin API Router.

Provides endpoints for application settings and release management.

All endpoints require PIN authentication via X-Admin-PIN header.
"""
import json
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, HttpUrl, field_validator, ConfigDict
from sqlalchemy.orm import Session
import re

from app.database import get_db
from app.models.db_models import Release, Module, AppSettings
from app.utils.security import require_admin_pin


logger = logging.getLogger(__name__)
router = APIRouter()


# Request/Response Models

class SettingUpdate(BaseModel):
    """Model for updating a setting."""
    value: str  # JSON-encoded value


class ReleaseCreate(BaseModel):
    """Model for creating a release."""
    name: str
    jenkins_job_url: Optional[HttpUrl] = None
    is_active: bool = True

    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        """Validate release name format (semantic version)."""
        if not re.match(r'^\d+\.\d+\.\d+\.\d+$', v):
            raise ValueError('Release name must be semantic version (e.g., 7.0.0.0)')
        return v


class ReleaseUpdate(BaseModel):
    """Model for updating a release."""
    name: Optional[str] = None
    jenkins_job_url: Optional[HttpUrl] = None
    is_active: Optional[bool] = None

    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        """Validate release name format if provided."""
        if v and not re.match(r'^\d+\.\d+\.\d+\.\d+$', v):
            raise ValueError('Release name must be semantic version (e.g., 7.0.0.0)')
        return v


class ReleaseResponse(BaseModel):
    """Response model for release."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    jenkins_job_url: Optional[str]
    is_active: bool
    created_at: datetime
    module_count: int


class SettingResponse(BaseModel):
    """Response model for app setting."""
    key: str
    value: str  # JSON-encoded
    description: Optional[str]
    updated_at: datetime


# Settings Endpoints

@router.get("/settings", response_model=List[SettingResponse])
@require_admin_pin
async def get_all_settings(request: Request, db: Session = Depends(get_db)):
    """
    Get all application settings.

    Requires X-Admin-PIN header for authentication.

    Args:
        request: FastAPI request object
        db: Database session

    Returns:
        List of all settings
    """
    settings = db.query(AppSettings).all()

    return [
        SettingResponse(
            key=s.key,
            value=s.value,
            description=s.description,
            updated_at=s.updated_at
        )
        for s in settings
    ]


@router.get("/settings/{key}", response_model=SettingResponse)
@require_admin_pin
async def get_setting(request: Request, key: str, db: Session = Depends(get_db)):
    """
    Get a specific setting by key.

    Requires X-Admin-PIN header for authentication.

    Args:
        request: FastAPI request object
        key: Setting key
        db: Database session

    Returns:
        Setting value and metadata
    """
    setting = db.query(AppSettings).filter(AppSettings.key == key).first()

    if not setting:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")

    return SettingResponse(
        key=setting.key,
        value=setting.value,
        description=setting.description,
        updated_at=setting.updated_at
    )


@router.put("/settings/{key}")
@require_admin_pin
async def update_setting(
    request: Request,
    key: str,
    update: SettingUpdate,
    db: Session = Depends(get_db)
):
    """
    Update a setting value.

    Requires X-Admin-PIN header for authentication.

    Args:
        request: FastAPI request object
        key: Setting key
        update: New value (JSON-encoded)
        db: Database session

    Returns:
        Updated setting
    """
    setting = db.query(AppSettings).filter(AppSettings.key == key).first()

    if not setting:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")

    # Validate JSON
    try:
        json.loads(update.value)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Value must be valid JSON")

    # Update setting
    setting.value = update.value
    setting.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(setting)

    # If updating polling settings, update scheduler
    if key in ['AUTO_UPDATE_ENABLED', 'POLLING_INTERVAL_MINUTES']:
        auto_update_setting = db.query(AppSettings).filter(
            AppSettings.key == 'AUTO_UPDATE_ENABLED'
        ).first()
        interval_setting = db.query(AppSettings).filter(
            AppSettings.key == 'POLLING_INTERVAL_MINUTES'
        ).first()

        auto_update_enabled = json.loads(auto_update_setting.value) if auto_update_setting else True
        interval_minutes = json.loads(interval_setting.value) if interval_setting else 15

        from app.tasks.scheduler import update_polling_schedule
        update_polling_schedule(auto_update_enabled, interval_minutes)

    return {
        'key': setting.key,
        'value': setting.value,
        'description': setting.description,
        'updated_at': setting.updated_at,
        'message': 'Setting updated successfully'
    }


@router.post("/settings")
@require_admin_pin
async def create_setting(
    request: Request,
    key: str,
    update: SettingUpdate,
    description: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Create a new setting.

    Requires X-Admin-PIN header for authentication.

    Args:
        request: FastAPI request object
        key: Setting key
        update: Value (JSON-encoded)
        description: Setting description
        db: Database session

    Returns:
        Created setting
    """
    # Check if exists
    existing = db.query(AppSettings).filter(AppSettings.key == key).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Setting '{key}' already exists")

    # Validate JSON
    try:
        json.loads(update.value)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Value must be valid JSON")

    # Create setting
    setting = AppSettings(
        key=key,
        value=update.value,
        description=description
    )

    db.add(setting)
    db.commit()
    db.refresh(setting)

    return {
        'key': setting.key,
        'value': setting.value,
        'description': setting.description,
        'updated_at': setting.updated_at,
        'message': 'Setting created successfully'
    }


# Release Management Endpoints

@router.get("/releases", response_model=List[ReleaseResponse])
@require_admin_pin
async def get_all_releases(request: Request, db: Session = Depends(get_db)):
    """
    Get all releases with module counts.

    Requires X-Admin-PIN header for authentication.

    Args:
        request: FastAPI request object
        db: Database session

    Returns:
        List of releases
    """
    releases = db.query(Release).all()

    return [
        ReleaseResponse(
            id=r.id,
            name=r.name,
            jenkins_job_url=r.jenkins_job_url,
            is_active=r.is_active,
            created_at=r.created_at,
            module_count=len(r.modules)
        )
        for r in releases
    ]


@router.get("/releases/{release_id}", response_model=ReleaseResponse)
@require_admin_pin
async def get_release(request: Request, release_id: int, db: Session = Depends(get_db)):
    """
    Get a specific release by ID.

    Requires X-Admin-PIN header for authentication.

    Args:
        request: FastAPI request object
        release_id: Release ID
        db: Database session

    Returns:
        Release details
    """
    release = db.query(Release).filter(Release.id == release_id).first()

    if not release:
        raise HTTPException(status_code=404, detail=f"Release {release_id} not found")

    return ReleaseResponse(
        id=release.id,
        name=release.name,
        jenkins_job_url=release.jenkins_job_url,
        is_active=release.is_active,
        created_at=release.created_at,
        module_count=len(release.modules)
    )


@router.post("/releases", response_model=ReleaseResponse)
@require_admin_pin
async def create_release(
    request: Request,
    release: ReleaseCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new release.

    Requires X-Admin-PIN header for authentication.

    Args:
        request: FastAPI request object
        release: Release data
        db: Database session

    Returns:
        Created release
    """
    # Check if exists
    existing = db.query(Release).filter(Release.name == release.name).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Release '{release.name}' already exists"
        )

    # Create release
    new_release = Release(
        name=release.name,
        jenkins_job_url=release.jenkins_job_url,
        is_active=release.is_active
    )

    db.add(new_release)
    db.commit()
    db.refresh(new_release)

    return ReleaseResponse(
        id=new_release.id,
        name=new_release.name,
        jenkins_job_url=new_release.jenkins_job_url,
        is_active=new_release.is_active,
        created_at=new_release.created_at,
        module_count=0
    )


@router.put("/releases/{release_id}", response_model=ReleaseResponse)
@require_admin_pin
async def update_release(
    request: Request,
    release_id: int,
    update: ReleaseUpdate,
    db: Session = Depends(get_db)
):
    """
    Update a release.

    Requires X-Admin-PIN header for authentication.

    Args:
        request: FastAPI request object
        release_id: Release ID
        update: Updated fields
        db: Database session

    Returns:
        Updated release
    """
    release = db.query(Release).filter(Release.id == release_id).first()

    if not release:
        raise HTTPException(status_code=404, detail=f"Release {release_id} not found")

    # Update fields
    if update.name is not None:
        # Check if new name conflicts
        existing = db.query(Release).filter(
            Release.name == update.name,
            Release.id != release_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Release '{update.name}' already exists"
            )
        release.name = update.name

    if update.jenkins_job_url is not None:
        release.jenkins_job_url = update.jenkins_job_url

    if update.is_active is not None:
        release.is_active = update.is_active

    release.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(release)

    return ReleaseResponse(
        id=release.id,
        name=release.name,
        jenkins_job_url=release.jenkins_job_url,
        is_active=release.is_active,
        created_at=release.created_at,
        module_count=len(release.modules)
    )


@router.delete("/releases/{release_id}")
@require_admin_pin
async def delete_release(request: Request, release_id: int, db: Session = Depends(get_db)):
    """
    Delete a release and all associated data (cascade).

    Requires X-Admin-PIN header for authentication.

    Args:
        request: FastAPI request object
        release_id: Release ID
        db: Database session

    Returns:
        Deletion confirmation
    """
    release = db.query(Release).filter(Release.id == release_id).first()

    if not release:
        raise HTTPException(status_code=404, detail=f"Release {release_id} not found")

    release_name = release.name
    module_count = len(release.modules)

    # Delete release (cascades to modules, jobs, test_results)
    db.delete(release)
    db.commit()

    return {
        'message': f'Release {release_name} deleted successfully',
        'modules_deleted': module_count
    }
