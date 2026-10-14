#!/usr/bin/env python3
"""
scripts/check_llm.py
====================
Utility script to verify connectivity to configured LLM providers.
Sends a tiny JSON test request to each configured provider and prints
OK/FAIL with latency per provider, without printing any API keys.

Usage:
    python backend/scripts/check_llm.py
"""

import json
import os
import sys
import time

# Ensure backend root is on sys.path so 'app' imports work
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_root = os.path.abspath(os.path.join(current_dir, ".."))
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

from app.agent.llm_client import sanitize_error_message
from app.agent.providers import get_provider
from app.config import settings


def check_providers() -> None:
    print("=" * 60)
    print("LLM Provider Health & Latency Probe")
    print(f"Fallback Order: {settings.llm_providers}")
    print("=" * 60)

    provider_names = [p.strip().lower() for p in settings.llm_providers.split(",") if p.strip()]

    test_sys_instruction = "You are a diagnostic healthcheck assistant. Always respond with valid JSON."
    test_prompt = '{"health_check": true, "respond": "ok"}'

    for name in provider_names:
        try:
            provider = get_provider(name)
        except Exception as e:
            sanitized = sanitize_error_message(str(e))
            print(f"[{name.upper()}] SKIPPED: Error instantiating provider: {sanitized}")
            continue

        if not provider.is_configured:
            print(f"[{name.upper()}] SKIPPED: Not configured (missing API key or model)")
            continue

        model_name = provider.model or "unknown-model"
        print(f"[{name.upper()}] Pinging {model_name}...", end=" ", flush=True)

        t_start = time.perf_counter()
        try:
            raw_text, tokens, prov_name, used_model = provider.generate_json(
                system_instruction=test_sys_instruction,
                prompt=test_prompt,
                timeout_sec=15,
            )
            # Verify JSON parseability
            parsed = json.loads(raw_text)
            latency_ms = (time.perf_counter() - t_start) * 1000
            total_toks = tokens.get("total_tokens", 0)
            print(f"OK ({latency_ms:.1f}ms, {total_toks} tokens)")
        except Exception as e:
            latency_ms = (time.perf_counter() - t_start) * 1000
            err_msg = sanitize_error_message(str(e))
            print(f"FAIL ({latency_ms:.1f}ms): {err_msg}")

    print("=" * 60)


if __name__ == "__main__":
    check_providers()
