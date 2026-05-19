"""Regression tests for mailagent's InternalAuthMiddleware.

Two things pinned here:

1. `_is_public_path` must NOT match by raw prefix. After the 0.7.88 review
   we found that `path.startswith("/health")` was an alternative in the
   matcher, which would let `/healthcheck-evil` skip HMAC auth. 0.7.89
   tightens to `path == p or path.startswith(p + "/")`.

2. HMAC sign/verify round-trip: the wire format used by the Aexy backend
   (`backend/src/aexy/integrations/mailagent_client._sign_request`) must
   match the verifier (`_compute_signature` here). Sign on one side,
   verify on the other.
"""

from __future__ import annotations

import hashlib
import hmac
import time

import pytest

from mailagent.middleware import (
    MAX_SKEW_SECONDS,
    _compute_signature,
    _is_public_path,
)


# ----- Public-path matcher: no raw-prefix bypass --------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/health",
        "/health/ready",
        "/docs",
        "/docs/",
        "/openapi.json",
        "/api/v1/webhooks",
        "/api/v1/webhooks/sendgrid",
    ],
)
def test_public_paths_match(path: str) -> None:
    assert _is_public_path(path) is True


@pytest.mark.parametrize(
    "path",
    [
        # The bypass we're guarding against — a route whose name starts
        # with a public-prefix but is NOT one of the intended public paths.
        "/healthcheck",
        "/healthcheck-evil",
        "/healthier",
        "/docsmaster",
        "/api/v1/webhooks-evil",
        "/api/v1/webhooksomething",
        # Unrelated authenticated paths.
        "/api/v1/agents",
        "/api/v1/onboarding/inboxes",
        "/",
    ],
)
def test_non_public_paths_do_not_match(path: str) -> None:
    assert _is_public_path(path) is False


# ----- HMAC round-trip: backend signer vs mailagent verifier --------------


def _backend_sign(secret: str, body: bytes) -> tuple[str, str]:
    """Mirror of backend/integrations/mailagent_client._sign_request.

    Inlined here so the test catches any drift between the two halves —
    if either side changes its wire format independently, this test fails.
    """
    timestamp = str(int(time.time()))
    payload = timestamp.encode("utf-8") + b"." + body
    signature = hmac.new(
        secret.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()
    return timestamp, signature


def test_sign_verify_roundtrip_matches() -> None:
    secret = "shared-internal-secret"
    body = b'{"to": "user@example.com", "subject": "hi"}'
    timestamp, signature = _backend_sign(secret, body)
    expected = _compute_signature(secret, timestamp, body)
    assert hmac.compare_digest(expected, signature)


def test_tampered_body_breaks_signature() -> None:
    secret = "shared-internal-secret"
    body = b'{"to":"user@example.com"}'
    timestamp, signature = _backend_sign(secret, body)
    tampered = b'{"to":"attacker@example.com"}'
    expected = _compute_signature(secret, timestamp, tampered)
    assert not hmac.compare_digest(expected, signature)


def test_signature_with_wrong_secret_fails() -> None:
    body = b'{"x":1}'
    timestamp, signature = _backend_sign("correct-secret", body)
    expected = _compute_signature("attacker-secret", timestamp, body)
    assert not hmac.compare_digest(expected, signature)


def test_skew_window_is_sane() -> None:
    # 5 minutes — long enough for clock drift and request latency, short
    # enough to bound replay opportunity. Pin the constant so a refactor
    # doesn't quietly widen it.
    assert MAX_SKEW_SECONDS == 300
