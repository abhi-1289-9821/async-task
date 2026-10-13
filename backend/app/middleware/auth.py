"""
middleware/auth.py
==================
Bearer token authentication and role-based access control.

Requirement: Authorization: Bearer <token>
Tokens configured via environment variables:
  - settings.demo_reviewer_token -> role: "REVIEWER"
  - settings.demo_viewer_token   -> role: "VIEWER"

Endpoints can require:
  - get_current_user: requires valid token (either role)
  - require_reviewer: requires role == "REVIEWER"
"""

import secrets
from typing import Annotated
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.config import settings


security = HTTPBearer(auto_error=False)


class AuthUser(BaseModel):
    identity: str
    role: str  # "REVIEWER" or "VIEWER"


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    request: Request,
) -> AuthUser:
    """
    Validates Bearer token from Authorization header using constant-time comparison.
    Returns AuthUser with distinct reviewer identity if provided, otherwise raises 401.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization: Bearer <token> header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # Check reviewer token with constant-time comparison
    if secrets.compare_digest(token, settings.demo_reviewer_token):
        custom_id = request.headers.get("x-reviewer-identity") or request.headers.get("x-reviewer-email")
        identity = custom_id.strip() if custom_id else "reviewer@acmebilling.com"
        return AuthUser(identity=identity, role="REVIEWER")

    # Check viewer token with constant-time comparison
    if secrets.compare_digest(token, settings.demo_viewer_token):
        custom_id = request.headers.get("x-viewer-identity") or request.headers.get("x-viewer-email")
        identity = custom_id.strip() if custom_id else "viewer@acmebilling.com"
        return AuthUser(identity=identity, role="VIEWER")

    # Invalid token
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_reviewer(
    user: Annotated[AuthUser, Depends(get_current_user)]
) -> AuthUser:
    """
    Requires the authenticated user to hold the REVIEWER role.
    Raises 403 Forbidden if the user only has the VIEWER role.
    """
    if user.role != "REVIEWER":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: This action requires the REVIEWER role",
        )
    return user
