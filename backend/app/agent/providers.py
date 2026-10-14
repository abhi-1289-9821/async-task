"""
agent/providers.py
==================
Pluggable LLM provider abstractions supporting multi-provider fallback:
- GeminiProvider via google-genai
- OpenAICompatProvider via httpx (Groq, OpenRouter)

All providers implement a common interface:
    generate_json(system_instruction, prompt, timeout_sec) -> (text, token_usage_dict, provider_name, model_name)
"""

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def extract_json_text(text: str) -> str:
    """Strips markdown code fences (```json ... ```) and whitespace from text."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()
    return text


def classify_error(e: Exception) -> tuple[str, bool]:
    """
    Classifies an exception into a standardized error type and determines
    whether the provider should be retried once.
    Returns (error_type, should_retry_once).
    - 429, 5xx, timeouts -> should_retry_once = True
    - 401, 403, 404, invalid JSON -> should_retry_once = False
    """
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        if code in (401, 403):
            return (f"{code}_AUTH_ERROR", False)
        if code == 404:
            return ("404_NOT_FOUND", False)
        if code == 429:
            return ("429_RATE_LIMIT", True)
        if 500 <= code <= 599:
            return (f"{code}_SERVER_ERROR", True)
        return (f"{code}_HTTP_ERROR", False)

    if isinstance(e, (httpx.TimeoutException, TimeoutError)):
        return ("TIMEOUT", True)

    if isinstance(e, json.JSONDecodeError):
        return ("INVALID_JSON", False)

    # Inspect status code attributes on third-party errors (e.g. google-genai APIError)
    status_code = getattr(e, "code", None) or getattr(e, "status_code", None)
    if status_code is not None:
        try:
            status_code = int(status_code)
            if status_code in (401, 403):
                return (f"{status_code}_AUTH_ERROR", False)
            if status_code == 404:
                return ("404_NOT_FOUND", False)
            if status_code == 429:
                return ("429_RATE_LIMIT", True)
            if 500 <= status_code <= 599:
                return (f"{status_code}_SERVER_ERROR", True)
        except (ValueError, TypeError):
            pass

    err_str = str(e).lower()
    if re.search(r"\b(401|403)\b", err_str) or "unauthorized" in err_str or "forbidden" in err_str:
        return ("401_AUTH_ERROR", False)
    if re.search(r"\b404\b", err_str) or "not found" in err_str or "not_found" in err_str:
        return ("404_NOT_FOUND", False)
    if re.search(r"\b429\b", err_str) or "resource_exhausted" in err_str or "quota" in err_str or "rate limit" in err_str:
        return ("429_RATE_LIMIT", True)
    if re.search(r"\b(500|502|503|504)\b", err_str) or "server error" in err_str:
        return ("500_SERVER_ERROR", True)
    if "timeout" in err_str or "timed out" in err_str:
        return ("TIMEOUT", True)

    return ("API_ERROR", False)


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier, e.g. 'gemini', 'groq', 'openrouter'."""
        pass

    @property
    @abstractmethod
    def model(self) -> str:
        """Configured model name."""
        pass

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """True if the provider has a non-empty API key and model configured."""
        pass

    @abstractmethod
    def generate_json(
        self,
        system_instruction: str,
        prompt: str,
        timeout_sec: int = 15,
    ) -> tuple[str, dict[str, int], str, str]:
        """
        Executes a prompt requesting a JSON response.
        Returns:
            (raw_text, token_usage_dict, provider_name, model_name)
        """
        pass


class GeminiProvider(LLMProvider):
    """Google Gemini provider using the official google-genai SDK."""

    def __init__(self, api_key: str, model: str):
        self._api_key = api_key or ""
        self._model = model or ""
        self._name = "gemini"

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._model

    @property
    def is_configured(self) -> bool:
        placeholder_keys = (
            "your-gemini-api-key-here",
            "your_gemini_api_key_here",
            "",
        )
        return bool(self._api_key and self._api_key not in placeholder_keys and self._model)

    def generate_json(
        self,
        system_instruction: str,
        prompt: str,
        timeout_sec: int = 15,
    ) -> tuple[str, dict[str, int], str, str]:
        if not self._api_key or self._api_key in ("your-gemini-api-key-here", "your_gemini_api_key_here"):
            raise ValueError("GEMINI_API_KEY is not set or is a placeholder")
        if not self._model:
            raise ValueError("GEMINI_MODEL is not set")

        from google import genai
        from google.genai import types

        client = genai.Client(
            api_key=self._api_key,
            http_options=types.HttpOptions(timeout=int(timeout_sec * 1000)),
        )
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
        )
        response = client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=config,
        )
        tokens = {
            "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0) if response.usage_metadata else 0,
            "completion_tokens": getattr(response.usage_metadata, "candidates_token_count", 0) if response.usage_metadata else 0,
            "total_tokens": getattr(response.usage_metadata, "total_token_count", 0) if response.usage_metadata else 0,
        }
        text = response.text or ""
        return (extract_json_text(text), tokens, self.name, self.model)


class OpenAICompatProvider(LLMProvider):
    """
    OpenAI-compatible HTTP provider using httpx.
    Used for Groq (https://api.groq.com/openai/v1) and OpenRouter (https://openrouter.ai/api/v1).
    """

    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self._name = name
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key or ""
        self._model = model or ""
        self.transport = transport

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._model

    @property
    def is_configured(self) -> bool:
        placeholder_keys = (
            f"your-{self._name}-api-key-here",
            f"your_{self._name}_api_key_here",
            "",
        )
        return bool(self._api_key and self._api_key not in placeholder_keys and self._model)

    def generate_json(
        self,
        system_instruction: str,
        prompt: str,
        timeout_sec: int = 15,
    ) -> tuple[str, dict[str, int], str, str]:
        if not self._api_key:
            raise ValueError(f"{self._name.upper()}_API_KEY is not set")
        if not self._model:
            raise ValueError(f"{self._name.upper()}_MODEL is not set")

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        messages = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": prompt},
        ]
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }

        with httpx.Client(transport=self.transport, timeout=float(timeout_sec)) as client:
            resp = client.post(url, headers=headers, json=payload)

            # If model does not support response_format (HTTP 400 mentioning it), retry once without it
            if resp.status_code == 400:
                err_text = resp.text.lower()
                if "response_format" in err_text or "json_object" in err_text:
                    logger.info(
                        "Provider %s (%s) rejected response_format; retrying without it and parsing JSON from text",
                        self.name,
                        self.model,
                    )
                    payload_no_format = {
                        "model": self._model,
                        "messages": messages,
                        "temperature": 0,
                    }
                    resp = client.post(url, headers=headers, json=payload_no_format)

            resp.raise_for_status()
            data = resp.json()

        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError(f"Provider {self.name} returned response with no choices")

        content = choices[0].get("message", {}).get("content", "")
        extracted = extract_json_text(content)

        usage = data.get("usage", {})
        tokens = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
        return (extracted, tokens, self.name, self.model)


def get_provider(name: str) -> LLMProvider:
    """Factory creating the appropriate LLMProvider instance based on name and settings."""
    name_clean = name.strip().lower()
    if name_clean == "gemini":
        return GeminiProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
        )
    elif name_clean == "groq":
        return OpenAICompatProvider(
            name="groq",
            base_url="https://api.groq.com/openai/v1",
            api_key=settings.groq_api_key,
            model=settings.groq_model,
        )
    elif name_clean == "openrouter":
        return OpenAICompatProvider(
            name="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.openrouter_api_key,
            model=settings.openrouter_model,
        )
    else:
        raise ValueError(f"Unknown LLM provider: '{name}'")


def has_configured_provider() -> bool:
    """Returns True if mock mode is active, or at least one configured provider has a key."""
    if settings.llm_mode == "mock":
        return True
    provider_names = [p.strip().lower() for p in settings.llm_providers.split(",") if p.strip()]
    for p_name in provider_names:
        try:
            p = get_provider(p_name)
            if p.is_configured:
                return True
        except Exception:
            continue
    return False
