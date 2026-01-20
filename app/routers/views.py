"""
View routes for rendering HTML pages.
Provides server-rendered Jinja2 templates for the frontend.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import os

router = APIRouter()

# Get the project root directory (two levels up from this file)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
templates_dir = os.path.join(BASE_DIR, "templates")

# Initialize Jinja2 templates
templates = Jinja2Templates(directory=templates_dir)


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """
    Render the main dashboard page.

    Returns:
        HTMLResponse: Rendered dashboard.html template
    """
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request}
    )


@router.get("/trends/{release}/{module}", response_class=HTMLResponse)
async def trends_page(request: Request, release: str, module: str):
    """
    Render the trends page for a specific release/module.

    Args:
        request: FastAPI request object
        release: Release name
        module: Module name

    Returns:
        HTMLResponse: Rendered trends.html template
    """
    response = templates.TemplateResponse(
        "trends.html",
        {
            "request": request,
            "release": release,
            "module": module
        }
    )
    # Prevent aggressive browser caching of HTML
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@router.get("/jobs/{release}/{module}/{job_id}", response_class=HTMLResponse)
async def job_details_page(request: Request, release: str, module: str, job_id: str):
    """
    Render the job details page for a specific job.

    Args:
        request: FastAPI request object
        release: Release name
        module: Module name
        job_id: Job ID

    Returns:
        HTMLResponse: Rendered job_details.html template
    """
    return templates.TemplateResponse(
        "job_details.html",
        {
            "request": request,
            "release": release,
            "module": module,
            "job_id": job_id
        }
    )


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    """
    Render the admin settings page.

    Note: This is a placeholder for Phase 4.
    In Phase 4, this will provide polling controls and release management.

    Returns:
        HTMLResponse: Rendered admin.html template
    """
    return templates.TemplateResponse(
        "admin.html",
        {"request": request}
    )


@router.get("/search", response_class=HTMLResponse)
async def search_page(request: Request):
    """
    Render the global test case search page.

    Allows searching for test cases by test_case_id, testrail_id, or testcase_name
    and viewing execution history across all releases and modules.

    Returns:
        HTMLResponse: Rendered search.html template
    """
    return templates.TemplateResponse(
        "search.html",
        {"request": request}
    )
