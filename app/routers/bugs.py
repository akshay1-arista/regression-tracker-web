"""
Bug Management Router - Admin endpoints for bug tracking.

Provides endpoints for manual bug updates and status monitoring.
All endpoints require PIN authentication via X-Admin-PIN header.
"""
import logging
from typing import Dict
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.bug_updater_service import BugUpdaterService
from app.config import get_settings
from app.utils.security import require_admin_pin

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/update")
@require_admin_pin
async def trigger_bug_update(
    request: Request,
    db: Session = Depends(get_db)
) -> Dict:
    """
    Manually trigger bug mappings update.

    Requires X-Admin-PIN header for authentication.

    Args:
        request: FastAPI request object (required by decorator)
        db: Database session

    Returns:
        Update statistics and message

    Raises:
        HTTPException: If update fails
    """
    settings = get_settings()

    try:
        service = BugUpdaterService(
            db=db,
            jenkins_user=settings.JENKINS_USER,
            jenkins_token=settings.JENKINS_API_TOKEN
        )
        stats = service.update_bug_mappings()

        return {
            "success": True,
            "message": f"Updated {stats['bugs_updated']} bugs "
                      f"({stats['vlei_count']} VLEI, {stats['vleng_count']} VLENG) "
                      f"with {stats['mappings_created']} mappings",
            "stats": stats
        }
    except Exception as e:
        logger.error(f"Manual bug update failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")


@router.get("/status")
async def get_bug_status(
    db: Session = Depends(get_db)
) -> Dict:
    """
    Get bug tracking status and statistics.

    Public endpoint - no authentication required for status viewing.

    Args:
        db: Database session

    Returns:
        Bug counts and last update time
    """
    settings = get_settings()

    service = BugUpdaterService(
        db=db,
        jenkins_user=settings.JENKINS_USER,
        jenkins_token=settings.JENKINS_API_TOKEN
    )

    last_update = service.get_last_update_time()
    counts = service.get_bug_counts()

    return {
        "last_update": last_update.isoformat() if last_update else None,
        "total_bugs": counts['total'],
        "vlei_bugs": counts['vlei'],
        "vleng_bugs": counts['vleng']
    }
