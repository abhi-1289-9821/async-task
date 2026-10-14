"""
app/logging.py
==============
Structured JSON logging for HTTP requests and LangGraph agent workflow nodes.
Provides context-aware request_id tracking via contextvars.
"""

import json
import logging
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Optional
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# Context variable for correlating logs across a single request/execution
request_id_ctx: ContextVar[Optional[str]] = ContextVar("request_id_ctx", default=None)


class JSONFormatter(logging.Formatter):
    """Formats log records as structured, machine-parseable JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include request/correlation ID if set in context
        req_id = request_id_ctx.get()
        if req_id:
            log_entry["request_id"] = req_id

        # Include structured extra payload if passed
        if hasattr(record, "structured_data") and isinstance(record.structured_data, dict):
            log_entry.update(record.structured_data)

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


def setup_structured_logging(level: int = logging.INFO) -> None:
    """Configures the root and app loggers with JSON formatting."""
    root_logger = logging.getLogger()
    # Avoid duplicate handlers on reload
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root_logger.addHandler(handler)
    root_logger.setLevel(level)


logger = logging.getLogger("app.structured")


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that assigns a unique request ID, measures request duration,
    and writes structured JSON access logs.
    """

    async def dispatch(self, request: Request, call_next):
        # Read incoming X-Request-ID or generate new UUID
        req_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:12]}"
        token = request_id_ctx.set(req_id)

        start_time = time.perf_counter()
        status_code = 500
        try:
            response: Response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = req_id
            return response
        finally:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            # Skip high-frequency health checks from verbose logging if desired, or log all
            logger.info(
                f"{request.method} {request.url.path} -> {status_code} ({latency_ms}ms)",
                extra={
                    "structured_data": {
                        "type": "http_request",
                        "request_id": req_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": status_code,
                        "latency_ms": latency_ms,
                        "client_ip": request.client.host if request.client else "unknown",
                    }
                },
            )
            request_id_ctx.reset(token)


def log_agent_node_execution(
    run_id: str,
    case_id: str,
    node: str,
    latency_ms: float,
    status: str,
    token_usage: Optional[dict[str, int]] = None,
    details: Optional[dict[str, Any]] = None,
) -> None:
    """Emits structured JSON metrics for a single LangGraph agent node execution."""
    payload: dict[str, Any] = {
        "type": "agent_node_execution",
        "run_id": run_id,
        "case_id": case_id,
        "node": node,
        "latency_ms": round(latency_ms, 2),
        "status": status,
    }
    if token_usage:
        payload["token_usage"] = token_usage
    if details:
        payload["details"] = details

    logger.info(
        f"Agent node '{node}' finished in {latency_ms:.2f}ms with status {status}",
        extra={"structured_data": payload},
    )
