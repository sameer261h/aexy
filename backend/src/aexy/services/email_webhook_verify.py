"""Per-provider signature verification for inbound email webhooks.

WS-057: each of the four supported providers (AWS SES via SNS, SendGrid,
Mailgun, Postmark) has its own signing scheme. We verify those before
trusting the event payload — without this, an attacker can submit fake
Bounce / Complaint / Unsubscribe events that mutate `CampaignRecipient`
status and `EmailSubscriber.status` for any workspace whose message_id
they can guess (see WS-081 for the cross-tenant injection vector that
results when sig verification is absent).

WS-058: also validates SES `SubscribeURL` against the AWS hostname so a
crafted SubscriptionConfirmation can't trigger SSRF into internal
services.

By default (`webhooks_require_signing=True`) any provider with missing
config rejects the request — fail-closed. For local development you can
set `webhooks_require_signing=False` to fall back to accepting unsigned
events; the verifier logs a warning each time. Production must keep the
default.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
from urllib.parse import urlparse

from aexy.core.config import get_settings

logger = logging.getLogger(__name__)


def _missing_config(provider: str) -> bool:
    """Decide whether to accept (dev) or reject (prod) when keys are unset.

    Returns True when the caller should treat the request as VERIFIED despite
    missing config (dev mode), False when it should be rejected. In prod this
    is always False, so a forgotten secret fails closed rather than letting
    forged events through silently.
    """
    require = get_settings().webhooks_require_signing
    if require:
        logger.error(
            "Email webhook from %s rejected: missing settings.%s_webhook_* and "
            "webhooks_require_signing=True. Configure the provider secret to accept events.",
            provider,
            provider.lower(),
        )
        return False
    logger.warning(
        "Email webhook from %s accepted without signature verification — "
        "missing settings.%s_webhook_* and webhooks_require_signing=False. "
        "Do not run this configuration in production.",
        provider,
        provider.lower(),
    )
    return True


# ---------------------------------------------------------------------------
# AWS SES via SNS
# ---------------------------------------------------------------------------

# Only AWS SNS hosts may be auto-confirmed. The SubscribeURL is attacker-
# controlled when the SubscriptionConfirmation message itself isn't signed,
# so we also enforce a hostname allowlist as a belt-and-suspenders check.
_SNS_HOST_PATTERN = re.compile(r"^sns\.[a-z0-9-]+\.amazonaws\.com$", re.IGNORECASE)


def is_safe_sns_subscribe_url(url: str) -> bool:
    """Reject anything that isn't a real AWS SNS confirm endpoint (WS-058)."""
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False
    host = parsed.hostname or ""
    return bool(_SNS_HOST_PATTERN.match(host))


def is_allowed_sns_topic(topic_arn: str | None) -> bool:
    """Topic ARN must be in the configured allowlist.

    Without this, an attacker who is *also* allowed to publish to a different
    AWS account's SNS topic could pump events at our endpoint. The allowlist
    pins inbound events to topics we own.
    """
    if not topic_arn:
        return False
    allowlist = (get_settings().ses_sns_topic_arn_allowlist or "").strip()
    if not allowlist:
        return _missing_config("SES")
    allowed = {arn.strip() for arn in allowlist.split(",") if arn.strip()}
    return topic_arn in allowed


# ---------------------------------------------------------------------------
# SendGrid (Twilio Email Event Webhook signature)
# ---------------------------------------------------------------------------

def verify_sendgrid_signature(
    body: bytes,
    timestamp_header: str | None,
    signature_header: str | None,
) -> bool:
    """ECDSA verification of `X-Twilio-Email-Event-Webhook-Signature` over
    `timestamp + body`. Public key from settings.

    Returns True when configuration is missing (dev) — production
    deployments must set `sendgrid_webhook_public_key`.
    """
    public_key_b64 = get_settings().sendgrid_webhook_public_key.strip()
    if not public_key_b64:
        return _missing_config("SendGrid")
    if not timestamp_header or not signature_header:
        return False
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.serialization import load_der_public_key
        from cryptography.hazmat.primitives import hashes
        from cryptography.exceptions import InvalidSignature
    except ImportError:
        logger.error("cryptography package missing; cannot verify SendGrid signature")
        return False

    try:
        der = base64.b64decode(public_key_b64)
        public_key = load_der_public_key(der)
        signature = base64.b64decode(signature_header)
        payload = timestamp_header.encode("utf-8") + body
        try:
            public_key.verify(signature, payload, ec.ECDSA(hashes.SHA256()))
            return True
        except InvalidSignature:
            return False
    except Exception as exc:
        logger.exception("SendGrid signature verification failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Mailgun (HMAC over timestamp + token)
# ---------------------------------------------------------------------------

def verify_mailgun_signature(timestamp: str | None, token: str | None, signature: str | None) -> bool:
    """`HMAC-SHA256(signing_key, timestamp + token)` from Mailgun signature
    block. Returns True in dev mode when no signing key is configured."""
    signing_key = get_settings().mailgun_webhook_signing_key
    if not signing_key:
        return _missing_config("Mailgun")
    if not timestamp or not token or not signature:
        return False
    expected = hmac.new(
        signing_key.encode("utf-8"),
        (timestamp + token).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# Postmark (HTTP Basic Auth — Postmark posts with a configured user/pass)
# ---------------------------------------------------------------------------

def verify_postmark_basic_auth(authorization_header: str | None) -> bool:
    """Postmark's "webhook secret" is HTTP Basic Auth credentials configured
    on the Postmark server. We compare timing-safely against the configured
    `user:pass`."""
    expected = get_settings().postmark_webhook_basic_auth.strip()
    if not expected:
        return _missing_config("Postmark")
    if not authorization_header or not authorization_header.lower().startswith("basic "):
        return False
    try:
        encoded = authorization_header.split(" ", 1)[1].strip()
        decoded = base64.b64decode(encoded).decode("utf-8")
    except Exception:
        return False
    return hmac.compare_digest(decoded, expected)


# ---------------------------------------------------------------------------
# Workspace resolution from signed payload (WS-081)
# ---------------------------------------------------------------------------

def workspace_id_from_sender(db_sync, sender_address: str | None) -> tuple[str | None, str | None]:
    """Resolve the (workspace_id, domain_id) tuple from the **signed** sender
    address rather than the caller-controlled `message_id` (WS-081).

    Once provider signature verification has succeeded, the `from` /
    `mail.source` field in the payload is trustworthy. Match its domain
    against our `SendingDomain` catalog to pin the event to a workspace
    without a `message_id` lookup oracle."""
    if not sender_address or "@" not in sender_address:
        return None, None
    domain = sender_address.rsplit("@", 1)[1].lower().strip().rstrip(">")
    if not domain:
        return None, None

    from sqlalchemy import select
    from aexy.models.email_infrastructure import SendingDomain

    result = db_sync.execute(
        select(SendingDomain).where(SendingDomain.domain == domain)
    )
    sd = result.scalar_one_or_none()
    if not sd:
        return None, None
    return str(sd.workspace_id), str(sd.id)
