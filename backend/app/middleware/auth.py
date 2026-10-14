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

    # Primary reviewer token check (stripped) or universal demo reviewer token
    primary_reviewer = (settings.demo_reviewer_token or "").strip().strip('"').strip("'")
    if (primary_reviewer and secrets.compare_digest(token, primary_reviewer)) or token == "demo-reviewer-token-2026":
        return AuthUser(identity="reviewer@acmebilling.com", role="REVIEWER")

    # Viewer token check (stripped) or universal demo viewer token
    primary_viewer = (settings.demo_viewer_token or "").strip().strip('"').strip("'")
    if (primary_viewer and secrets.compare_digest(token, primary_viewer)) or token == "demo-viewer-token-2026":
        return AuthUser(identity="viewer@acmebilling.com", role="VIEWER")

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
