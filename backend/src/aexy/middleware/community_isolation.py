"""Community-account isolation middleware.

Wall off "community" accounts — outsiders who signed in solely to post on a
public community forum — from the entire internal product. This is the
belt-and-suspenders layer: workspace endpoints already reject the low-ranked
``community`` role via ``check_permission``, but a middleware is the only place
that can't be bypassed by a router that forgot to add a guard.

The account type travels as a JWT claim (minted in ``create_access_token``), so
the check is a cheap stateless decode with no DB hit. Only ``account_type ==
"community"`` is ever blocked; legacy tokens without the claim, API tokens, and
anonymous requests are all treated as non-community and pass through.

A community token may reach ONLY:
  * ``/api/v1/auth/*``          — the OAuth flows themselves
  * ``/api/v1/public/*``        — public reads + the authenticated reply endpoint
  * ``/api/v1/developers/me``   — the caller's own profile (the frontend app-shell
                                  guard reads ``account_type`` from here)

Everything else under ``/api/v1`` returns 403. Non-API paths (health, docs) are
never inspected.
"""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

_API_PREFIX = "/api/v1"

# Path prefixes a community account may reach.
_ALLOWED_PREFIXES = (
    "/api/v1/auth",
    "/api/v1/public",
)
# Exact paths a community account may reach (no sub-paths).
_ALLOWED_EXACT = frozenset({"/api/v1/developers/me"})


class CommunityIsolationMiddleware(BaseHTTPMiddleware):
    """Deny community-only accounts access to internal API endpoints."""

    def __init__(self, app, secret_key: str, algorithm: str = "HS256"):
        super().__init__(app)
        self.secret_key = secret_key
        self.algorithm = algorithm

    def _account_type(self, request: Request) -> str | None:
        """Return the JWT ``account_type`` claim, or None if not a decodable JWT."""
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None
        token = auth_header[7:]
        # API tokens (aexy_ prefix) are always internal-user credentials.
        if token.startswith("aexy_"):
            return None
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
        except JWTError:
            # Let the normal auth dependency produce the 401; don't mask it here.
            return None
        return payload.get("account_type")

    @staticmethod
    def _is_allowed(path: str) -> bool:
        if path in _ALLOWED_EXACT:
            return True
        return any(path.startswith(p) for p in _ALLOWED_PREFIXES)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Only inspect API traffic; static/health/docs are never community-gated.
        if path.startswith(_API_PREFIX) and self._account_type(request) == "community":
            if not self._is_allowed(path):
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": (
                            "This account can only access the public community. "
                            "Ask a workspace admin for an invite to use the app."
                        )
                    },
                )
        return await call_next(request)
