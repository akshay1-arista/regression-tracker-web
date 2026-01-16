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
    return templates.TemplateResponse(
        "trends.html",
        {
            "request": request,
            "release": release,
            "module": module
        }
    )


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
        HTMLResponse: Simple admin page placeholder
    """
    return HTMLResponse(
        content="""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Admin - Regression Tracker</title>
            <link rel="stylesheet" href="/static/css/styles.css">
        </head>
        <body>
            <nav class="navbar">
                <div class="nav-container">
                    <a href="/" class="nav-brand">
                        <h1>Regression Tracker</h1>
                    </a>
                    <ul class="nav-menu">
                        <li class="nav-item">
                            <a href="/" class="nav-link">Dashboard</a>
                        </li>
                        <li class="nav-item">
                            <a href="/admin" class="nav-link active">Admin</a>
                        </li>
                    </ul>
                </div>
            </nav>
            <main class="container">
                <div class="empty-state">
                    <h2>Admin Settings</h2>
                    <p>Admin interface will be implemented in Phase 4.</p>
                    <p>This will include:</p>
                    <ul style="text-align: left; max-width: 500px; margin: 20px auto;">
                        <li>Jenkins polling configuration</li>
                        <li>Manual download trigger</li>
                        <li>Release management</li>
                        <li>Application settings</li>
                    </ul>
                </div>
            </main>
            <footer class="footer">
                <div class="footer-container">
                    <p>&copy; 2026 Regression Tracker | Powered by FastAPI + Alpine.js</p>
                </div>
            </footer>
        </body>
        </html>
        """,
        status_code=200
    )
