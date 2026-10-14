"""
routers/llm.py
==============
FastAPI endpoint for inspecting configured LLM providers without exposing keys.
"""

from typing import Annotated, Any
from fastapi import APIRouter, Depends

from app.agent.providers import get_provider
from app.config import settings
from app.middleware.auth import AuthUser, get_current_user

router = APIRouter(tags=["llm"])


@router.get("/api/llm/status")
def get_llm_status(
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> dict[str, Any]:
    """
    Returns configured status and model name for each provider.
    Accessible by any authenticated role (REVIEWER or VIEWER).
    Never exposes API keys or secrets.
    """
    provider_names = [p.strip().lower() for p in settings.llm_providers.split(",") if p.strip()]
    providers_list = []
    result: dict[str, Any] = {}

    for name in provider_names:
        try:
            prov = get_provider(name)
            is_conf = prov.is_configured
            model_name = prov.model or ""
        except Exception:
            is_conf = False
            model_name = ""

        info = {
            "name": name,
            "provider": name,
            "configured": is_conf,
            "model": model_name,
        }
        providers_list.append(info)
        result[name] = {"configured": is_conf, "model": model_name}

    result["providers"] = providers_list
    return result
