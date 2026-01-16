"""
Authentication utilities for API key validation.
"""
from typing import Optional
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader
from app.config import get_settings

# API Key header
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

settings = get_settings()


async def verify_api_key(api_key: Optional[str] = Security(api_key_header)) -> str:
    """
    Verify API key from request header.
    
    Args:
        api_key: API key from X-API-Key header
        
    Returns:
        The validated API key
        
    Raises:
        HTTPException: If API key is missing or invalid
    """
    # If no API key is configured, skip authentication
    if not settings.API_KEY:
        return "no-auth-required"
    
    # Check if API key is provided
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required. Provide X-API-Key header."
        )
    
    # Verify API key
    if api_key not in [settings.API_KEY, settings.ADMIN_API_KEY]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key"
        )
    
    return api_key


async def verify_admin_api_key(api_key: Optional[str] = Security(api_key_header)) -> str:
    """
    Verify admin API key from request header.
    
    Args:
        api_key: API key from X-API-Key header
        
    Returns:
        The validated admin API key
        
    Raises:
        HTTPException: If API key is missing or not an admin key
    """
    # If no admin API key is configured, skip authentication
    if not settings.ADMIN_API_KEY:
        return "no-auth-required"
    
    # Check if API key is provided
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin API key required. Provide X-API-Key header."
        )
    
    # Verify admin API key
    if api_key != settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin API key required"
        )
    
    return api_key
