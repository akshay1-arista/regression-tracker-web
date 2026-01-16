"""Helper utilities for the application."""
from typing import Optional, Dict
from fastapi import HTTPException


def escape_like_pattern(pattern: str) -> str:
    """
    Escape special LIKE characters to prevent injection.
    
    Args:
        pattern: The search pattern
    
    Returns:
        Escaped pattern safe for LIKE queries
    """
    return pattern.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


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
