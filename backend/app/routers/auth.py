"""
routers/auth.py
===============
Authentication profile endpoint returning authenticated identity, role, and permissions.
"""

from typing import Annotated
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import settings
from app.middleware.auth import AuthUser, get_current_user


router = APIRouter(prefix="/api/auth", tags=["auth"])


class AuthProfileResponse(BaseModel):
    identity: str
    role: str
    demo_mode: bool
    environment: str
    permissions: list[str]


@router.get("/me", response_model=AuthProfileResponse)
def get_current_user_profile(
    user: Annotated[AuthUser, Depends(get_current_user)],
):
    """
    Returns current authenticated user profile, active role, and system permissions.
    Available to any authenticated token (REVIEWER or VIEWER).
    """
    reviewer_perms = [
        "read:cases",
        "read:evidence",
        "read:calculations",
        "read:findings",
        "read:credits",
        "read:audit",
        "write:cases",
        "write:evidence",
        "run:calculations",
        "run:investigations",
        "review:findings",
        "approve:credits",
    ]
    viewer_perms = [
        "read:cases",
        "read:evidence",
        "read:calculations",
        "read:findings",
        "read:credits",
        "read:audit",
    ]

    return AuthProfileResponse(
        identity=user.identity,
        role=user.role,
        demo_mode=settings.demo_mode,
        environment=settings.environment,
        permissions=reviewer_perms if user.role == "REVIEWER" else viewer_perms,
    )
