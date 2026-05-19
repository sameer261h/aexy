"""Mailagent request-authentication middleware.

WS-077: Mailagent runs as a singleton service holding every workspace's
email-provider credentials. Without auth, any caller reachable at :8001 can
send mail through customer domains or read provider API keys. We require
every non-public route to carry an HMAC signature computed by the Aexy
backend with a shared secret.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from mailagent.config import get_settings


logger = logging.getLogger(__name__)


# Path prefixes that are intentionally public:
#   /health         - liveness/readiness probes (Kubernetes, ALB)
#   /docs, /redoc, /openapi.json - OpenAPI surface
#   /api/v1/webhooks - provider webhooks that verify their own signatures
PUBLIC_PREFIXES = (
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/webhooks",
)

# Reject requests whose timestamp drifts more than this many seconds from
# the server clock to prevent replays of an old signed body.
MAX_SKEW_SECONDS = 300


def _is_public_path(path: str) -> bool:
    # Match exact path or a child path. NEVER match by raw prefix — without
    # the trailing "/", "/healthcheck-evil" would slip past as a "/health"
    # match and skip HMAC auth entirely.
    return any(path == p or path.startswith(p + "/") for p in PUBLIC_PREFIXES)


def _compute_signature(secret: str, timestamp: str, body: bytes) -> str:
    """HMAC-SHA256 of `{timestamp}.{body}` keyed with the shared secret.

    Same shape as Slack's webhook signature (X-Slack-Signature). Tying the
    body in prevents replay even within the skew window, and tying the
    timestamp in caps how far back a captured signature can be replayed.
    """
    payload = timestamp.encode("utf-8") + b"." + body
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


class InternalAuthMiddleware(BaseHTTPMiddleware):
    """Reject any non-public request that doesn't carry a valid HMAC.

    Skipped entirely when `internal_secret` is empty (local dev). In that
    mode, mailagent is implicitly trusted — operators must keep :8001
    bound to localhost / the cluster's internal network only.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        settings = get_settings()
        secret = settings.internal_secret

        # No secret configured → dev mode, fall through. Log a startup
        # warning elsewhere; do not gate here.
        if not secret:
            return await call_next(request)

        if _is_public_path(request.url.path):
            return await call_next(request)

        timestamp = request.headers.get("X-Mailagent-Timestamp")
        signature = request.headers.get("X-Mailagent-Signature")
        if not timestamp or not signature:
            return JSONResponse(
                {"detail": "Missing X-Mailagent-Signature/Timestamp"},
                status_code=401,
            )

        # Timestamp must parse and fall within the skew window.
        try:
            ts_seconds = int(timestamp)
        except ValueError:
            return JSONResponse({"detail": "Bad signature timestamp"}, status_code=401)
        if abs(int(time.time()) - ts_seconds) > MAX_SKEW_SECONDS:
            return JSONResponse({"detail": "Signature timestamp out of range"}, status_code=401)

        body = await request.body()
        expected = _compute_signature(secret, timestamp, body)
        if not hmac.compare_digest(expected, signature):
            logger.warning("Mailagent signature mismatch on %s %s", request.method, request.url.path)
            return JSONResponse({"detail": "Invalid signature"}, status_code=401)

        # Replay the body so downstream handlers can read it again — Starlette
        # caches the parsed body internally once `request.body()` is called,
        # but for safety we re-stuff the receive channel.
        async def _receive():
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = _receive  # type: ignore[attr-defined]
        return await call_next(request)
