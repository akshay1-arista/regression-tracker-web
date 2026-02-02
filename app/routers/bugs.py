"""
Bug Management Router - Admin endpoints for bug tracking.

Provides endpoints for manual bug updates and status monitoring.
All endpoints require PIN authentication via X-Admin-PIN header.
"""
import logging
from typing import Dict, List, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi_cache.decorator import cache
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_

from app.database import get_db
from app.services.bug_updater_service import BugUpdaterService
from app.models.db_models import BugMetadata, BugTestcaseMapping, TestcaseMetadata, TestResult, Job
from app.config import get_settings
from app.utils.security import require_admin_pin

logger = logging.getLogger(__name__)
router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.post("/update")
@limiter.limit("2/hour")  # Max 2 updates per hour to prevent abuse
@require_admin_pin
async def trigger_bug_update(
    request: Request,
    db: Session = Depends(get_db)
) -> Dict:
    """
    Manually trigger bug mappings update.

    Rate limited to 2 requests per hour to prevent abuse.
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
            jenkins_token=settings.JENKINS_API_TOKEN,
            jenkins_bug_url=settings.JENKINS_BUG_DATA_URL,
            verify_ssl=settings.JENKINS_VERIFY_SSL
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


@router.get("/top-impacting")
@cache(expire=300)
async def get_top_impacting_bugs(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    Get top bugs sorted by number of associated test cases.

    Used to identify high-impact bugs (VLEI/VLENG) that affect many test cases.

    Args:
        limit: Maximum number of bugs to return (default: 20)
        db: Database session

    Returns:
        List of bugs with case counts
    """
    results = db.query(
        BugMetadata,
        func.count(BugTestcaseMapping.id).label('case_count')
    ).join(
        BugTestcaseMapping, BugMetadata.id == BugTestcaseMapping.bug_id
    ).filter(
        BugMetadata.is_active == True
    ).group_by(
        BugMetadata.id
    ).order_by(
        func.count(BugTestcaseMapping.id).desc()
    ).limit(limit).all()

    return [
        {
            "defect_id": bug.defect_id,
            "bug_type": bug.bug_type,
            "url": bug.url,
            "summary": bug.summary,
            "priority": bug.priority,
            "status": bug.status,
            "assignee": bug.assignee,
            "case_count": count
        }
        for bug, count in results
    ]


@router.get("/{defect_id}/testcases")
@cache(expire=60)
async def get_bug_testcases(
    defect_id: str,
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    Get test cases associated with a bug, including latest execution status.

    Args:
        defect_id: Bug ID (e.g., "VLEI-123")
        db: Database session

    Returns:
        List of test cases with metadata and latest status
    """
    # 1. Get mappings for this bug
    mappings = db.query(BugTestcaseMapping.case_id).join(
        BugMetadata, BugMetadata.id == BugTestcaseMapping.bug_id
    ).filter(
        BugMetadata.defect_id == defect_id
    ).all()

    if not mappings:
        return []

    case_ids = [m[0] for m in mappings]

    # 2. Find corresponding metadata
    # Case ID can match test_case_id OR testrail_id
    metadata_records = db.query(TestcaseMetadata).filter(
        or_(
            TestcaseMetadata.test_case_id.in_(case_ids),
            TestcaseMetadata.testrail_id.in_(case_ids)
        )
    ).all()

    if not metadata_records:
        # Return basic info if no metadata found (just the case IDs)
        return [{"test_case_id": cid, "latest_status": "UNKNOWN"} for cid in case_ids]

    # 3. Find latest execution for these test cases
    test_names = [m.testcase_name for m in metadata_records]

    # Subquery to find max ID per test_name to get latest result
    subquery = db.query(
        TestResult.test_name,
        func.max(TestResult.id).label('max_id')
    ).filter(
        TestResult.test_name.in_(test_names)
    ).group_by(
        TestResult.test_name
    ).subquery()

    latest_results = db.query(TestResult).join(
        subquery,
        (TestResult.test_name == subquery.c.test_name) &
        (TestResult.id == subquery.c.max_id)
    ).options(
        # Eager load job to avoid N+1 queries
        joinedload(TestResult.job).load_only(Job.job_id, Job.release_id)
    ).all()

    # Create lookup map
    result_map = {r.test_name: r for r in latest_results}

    # 4. Construct response
    response = []
    for meta in metadata_records:
        result = result_map.get(meta.testcase_name)
        
        job_info = None
        if result and result.job:
             # We need to fetch the release name too, but let's keep it simple for now
             # We can't easily get release name without another join in the main query
             # For now, just return job_id
             job_info = {
                 "job_id": result.job.job_id,
                 "id": result.job.id
             }

        response.append({
            "testcase_name": meta.testcase_name,
            "test_case_id": meta.test_case_id,
            "testrail_id": meta.testrail_id,
            "priority": meta.priority,
            "module": meta.module,
            "component": meta.component,
            "topology": meta.topology,
            "latest_status": result.status.value if result else "NOT_RUN",
            "latest_job": job_info,
            "latest_run_date": result.created_at.isoformat() if result else None
        })

    return response


@router.get("/status")
@cache(expire=300)  # Cache for 5 minutes (bug counts change infrequently)
async def get_bug_status(
    db: Session = Depends(get_db)
) -> Dict:
    """
    Get bug tracking status and statistics.

    Public endpoint - no authentication required for status viewing.
    Results cached for 5 minutes.

    Args:
        db: Database session

    Returns:
        Bug counts and last update time
    """
    settings = get_settings()

    service = BugUpdaterService(
        db=db,
        jenkins_user=settings.JENKINS_USER,
        jenkins_token=settings.JENKINS_API_TOKEN,
        jenkins_bug_url=settings.JENKINS_BUG_DATA_URL,
        verify_ssl=settings.JENKINS_VERIFY_SSL
    )

    last_update = service.get_last_update_time()
    counts = service.get_bug_counts()

    return {
        "last_update": last_update.isoformat() if last_update else None,
        "total_bugs": counts['total'],
        "vlei_bugs": counts['vlei'],
        "vleng_bugs": counts['vleng']
    }
