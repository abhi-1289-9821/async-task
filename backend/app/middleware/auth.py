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

    token = (credentials.credentials or "").strip().strip('"').strip("'")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization: Bearer <token> header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check multi-user reviewer tokens registry
    if settings.reviewer_tokens:
        for entry in settings.reviewer_tokens.split(","):
            if ":" in entry:
                tok, ident = entry.split(":", 1)
                if secrets.compare_digest(token, tok.strip().strip('"').strip("'")):
                    return AuthUser(identity=ident.strip(), role="REVIEWER")

    default_demo_tokens = ("demo-reviewer-token-2026", "demo-viewer-token-2026")

    # Primary reviewer token check using constant-time comparison
    primary_reviewer = (settings.demo_reviewer_token or "").strip().strip('"').strip("'")
    if primary_reviewer:
        if settings.demo_mode or primary_reviewer not in default_demo_tokens:
            if secrets.compare_digest(token, primary_reviewer):
                return AuthUser(identity="reviewer@fairbill.io", role="REVIEWER")

    # When demo_mode is enabled, allow default reviewer evaluation token via constant-time comparison
    if settings.demo_mode and secrets.compare_digest(token, "demo-reviewer-token-2026"):
        return AuthUser(identity="reviewer@fairbill.io", role="REVIEWER")

    # Primary viewer token check using constant-time comparison
    primary_viewer = (settings.demo_viewer_token or "").strip().strip('"').strip("'")
    if primary_viewer:
        if settings.demo_mode or primary_viewer not in default_demo_tokens:
            if secrets.compare_digest(token, primary_viewer):
                return AuthUser(identity="viewer@fairbill.io", role="VIEWER")

    # When demo_mode is enabled, allow default viewer evaluation token via constant-time comparison
    if settings.demo_mode and secrets.compare_digest(token, "demo-viewer-token-2026"):
        return AuthUser(identity="viewer@fairbill.io", role="VIEWER")

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
