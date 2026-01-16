"""
Security utilities for the application.

Provides credential management and PIN-based authentication.
"""
import os
import hashlib
import secrets
from functools import wraps
from typing import Optional

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse


def hash_pin(pin: str) -> str:
    """
    Hash a PIN using SHA-256.

    Args:
        pin: Plain text PIN

    Returns:
        Hex digest of hashed PIN
    """
    return hashlib.sha256(pin.encode()).hexdigest()


def verify_pin(pin: str, pin_hash: str) -> bool:
    """
    Verify a PIN against its hash.

    Args:
        pin: Plain text PIN to verify
        pin_hash: Expected hash

    Returns:
        True if PIN matches
    """
    return hashlib.sha256(pin.encode()).hexdigest() == pin_hash


def require_admin_pin(func):
    """
    Decorator to require PIN authentication for admin endpoints.

    Expects X-Admin-PIN header with the admin PIN.
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # Import here to avoid circular dependency
        from app.config import get_settings
        settings = get_settings()

        # Extract request from kwargs
        request: Optional[Request] = kwargs.get('request')
        if not request:
            # Try to find request in args
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break

        if not request:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Request object not found"
            )

        # Check for PIN header
        pin = request.headers.get('X-Admin-PIN')

        if not pin:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Admin PIN required"
            )

        # Verify PIN
        if not settings.ADMIN_PIN_HASH:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Admin PIN not configured"
            )

        if not verify_pin(pin, settings.ADMIN_PIN_HASH):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid admin PIN"
            )

        # PIN is valid, proceed
        return await func(*args, **kwargs)

    return wrapper


class CredentialsManager:
    """
    Manages secure access to sensitive credentials.

    Credentials are stored in environment variables, not in the database.
    """

    @staticmethod
    def get_jenkins_credentials() -> tuple[str, str, str]:
        """
        Get Jenkins credentials from environment variables.

        Returns:
            Tuple of (url, user, token)

        Raises:
            ValueError: If credentials are not configured
        """
        from app.config import get_settings

        settings = get_settings()

        if not all([settings.JENKINS_URL, settings.JENKINS_USER, settings.JENKINS_API_TOKEN]):
            raise ValueError(
                "Jenkins credentials not configured. "
                "Set JENKINS_URL, JENKINS_USER, and JENKINS_API_TOKEN environment variables."
            )

        return settings.JENKINS_URL, settings.JENKINS_USER, settings.JENKINS_API_TOKEN

    @staticmethod
    def validate_jenkins_credentials() -> bool:
        """
        Check if Jenkins credentials are configured.

        Returns:
            True if all credentials are set
        """
        try:
            CredentialsManager.get_jenkins_credentials()
            return True
        except ValueError:
            return False
