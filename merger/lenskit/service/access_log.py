"""Credential-safe HTTP access logging for the rLens service.

The middleware deliberately observes only ASGI protocol metadata required for
operational visibility.  It never reads request headers, cookies, query
strings, client addresses, or request/response bodies.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any


_ACCESS_LOGGER = logging.getLogger("uvicorn.error.rlens_access")
_MAX_METHOD_CHARS = 16
_MAX_ROUTE_CHARS = 256


def _bounded_ascii(value: object, *, fallback: str, max_chars: int) -> str:
    raw = str(value or fallback)[:max_chars]
    normalized = "".join(char if 0x20 <= ord(char) < 0x7F else "?" for char in raw)
    return normalized or fallback


def _route_template(scope: MutableMapping[str, Any]) -> str:
    """Return a code-defined route template, never the user-supplied URL path."""
    route = scope.get("route")
    template = getattr(route, "path", None)
    if not isinstance(template, str) or not template:
        return "<unmatched>"
    return _bounded_ascii(template, fallback="<unmatched>", max_chars=_MAX_ROUTE_CHARS)


class SafeAccessLogMiddleware:
    """Emit one bounded JSON record for each completed HTTP request.

    The downstream router may add ``scope["route"]`` while handling the request;
    logging after completion lets us use that static route template instead of
    the concrete, potentially sensitive request path.
    """

    def __init__(
        self,
        app: Callable[[MutableMapping[str, Any], Callable[..., Awaitable[dict[str, Any]]], Callable[..., Awaitable[None]]], Awaitable[None]],
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self.app = app
        self.logger = logger or _ACCESS_LOGGER

    async def __call__(
        self,
        scope: MutableMapping[str, Any],
        receive: Callable[..., Awaitable[dict[str, Any]]],
        send: Callable[..., Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status_code = 500

        async def capture_status(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                raw_status = message.get("status")
                if isinstance(raw_status, int) and 100 <= raw_status <= 599:
                    status_code = raw_status
            await send(message)

        try:
            await self.app(scope, receive, capture_status)
        finally:
            duration_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
            record = {
                "duration_ms": round(duration_ms, 3),
                "event": "http_access",
                "method": _bounded_ascii(
                    scope.get("method"), fallback="UNKNOWN", max_chars=_MAX_METHOD_CHARS
                ),
                "route": _route_template(scope),
                "status": status_code,
            }
            try:
                self.logger.info(
                    json.dumps(record, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
                )
            except Exception:
                # Observability is best-effort.  A broken custom handler must not
                # turn a completed HTTP response into an application failure.
                pass
