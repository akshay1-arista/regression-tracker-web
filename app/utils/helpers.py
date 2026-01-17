"""Helper utilities for the application."""
from typing import Optional, Dict
from fastapi import HTTPException


def escape_like_pattern(pattern: str) -> str:
    """
    Escape special LIKE characters to prevent injection.

    Escapes % and \ but NOT underscores, since:
    - Underscores are not a security risk in LIKE patterns
    - Users expect to search for literal underscores in test names
    - Without an ESCAPE clause, backslash escaping doesn't work in SQLite

    Args:
        pattern: The search pattern

    Returns:
        Escaped pattern safe for LIKE queries
    """
    # Only escape % and \ for security, not underscores for UX
    return pattern.replace('\\', '\\\\').replace('%', '\\%')


def not_found_error(
    resource_type: str,
    resource_id: str,
    parent: Optional[Dict[str, str]] = None
) -> HTTPException:
    """
    Create a standardized 404 error response.
    
    Args:
        resource_type: Type of resource (e.g., "Module", "Job")
        resource_id: ID of the resource
        parent: Optional parent resource info {"type": "Release", "id": "7.0.0.0"}
    
    Returns:
        HTTPException with standardized error message
    """
    detail = f"{resource_type} '{resource_id}' not found"
    if parent:
        detail += f" in {parent['type']} '{parent['id']}'"
    return HTTPException(status_code=404, detail=detail)


def validation_error(detail: str) -> HTTPException:
    """
    Create a standardized 400 validation error response.
    
    Args:
        detail: Error detail message
    
    Returns:
        HTTPException with validation error
    """
    return HTTPException(status_code=400, detail=detail)
