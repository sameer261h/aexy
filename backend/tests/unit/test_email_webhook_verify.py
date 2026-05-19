"""Regression tests for `email_webhook_verify`.

The original 0.7.85 helpers returned True when their respective env var was
unset, silently accepting unsigned events in production if any secret was
omitted. 0.7.89 introduces `webhooks_require_signing=True` (default) and
flips that behavior to fail-closed. These tests pin the default in place
so a future config refactor doesn't regress it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

import pytest

from aexy.core.config import get_settings
from aexy.services import email_webhook_verify as evw


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    # Force a fresh Settings() instance per test so env mutations take effect.
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ----- Fail-closed when keys are missing (the prod default) ----------------


def test_sendgrid_rejects_when_public_key_missing(monkeypatch):
    monkeypatch.setenv("WEBHOOKS_REQUIRE_SIGNING", "true")
    monkeypatch.setenv("SENDGRID_WEBHOOK_PUBLIC_KEY", "")
    assert evw.verify_sendgrid_signature(b"payload", "1", "sig") is False


def test_mailgun_rejects_when_signing_key_missing(monkeypatch):
    monkeypatch.setenv("WEBHOOKS_REQUIRE_SIGNING", "true")
    monkeypatch.setenv("MAILGUN_WEBHOOK_SIGNING_KEY", "")
    assert evw.verify_mailgun_signature("1", "tok", "sig") is False


def test_postmark_rejects_when_basic_auth_missing(monkeypatch):
    monkeypatch.setenv("WEBHOOKS_REQUIRE_SIGNING", "true")
    monkeypatch.setenv("POSTMARK_WEBHOOK_BASIC_AUTH", "")
    assert evw.verify_postmark_basic_auth("Basic dXNlcjpwYXNz") is False


def test_ses_topic_rejects_when_allowlist_missing(monkeypatch):
    monkeypatch.setenv("WEBHOOKS_REQUIRE_SIGNING", "true")
    monkeypatch.setenv("SES_SNS_TOPIC_ARN_ALLOWLIST", "")
    assert evw.is_allowed_sns_topic("arn:aws:sns:us-east-1:111:topic") is False


# ----- Dev override: explicit opt-in to fail-open ---------------------------


def test_sendgrid_dev_opt_in_returns_true(monkeypatch):
    monkeypatch.setenv("WEBHOOKS_REQUIRE_SIGNING", "false")
    monkeypatch.setenv("SENDGRID_WEBHOOK_PUBLIC_KEY", "")
    assert evw.verify_sendgrid_signature(b"x", "1", "sig") is True


def test_postmark_dev_opt_in_returns_true(monkeypatch):
    monkeypatch.setenv("WEBHOOKS_REQUIRE_SIGNING", "false")
    monkeypatch.setenv("POSTMARK_WEBHOOK_BASIC_AUTH", "")
    assert evw.verify_postmark_basic_auth(None) is True


# ----- Happy paths: real signatures verify --------------------------------


def test_mailgun_valid_signature_accepted(monkeypatch):
    monkeypatch.setenv("WEBHOOKS_REQUIRE_SIGNING", "true")
    monkeypatch.setenv("MAILGUN_WEBHOOK_SIGNING_KEY", "secret-key")
    timestamp = str(int(time.time()))
    token = "abc123"
    sig = hmac.new(
        b"secret-key",
        (timestamp + token).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    assert evw.verify_mailgun_signature(timestamp, token, sig) is True


def test_mailgun_tampered_signature_rejected(monkeypatch):
    monkeypatch.setenv("WEBHOOKS_REQUIRE_SIGNING", "true")
    monkeypatch.setenv("MAILGUN_WEBHOOK_SIGNING_KEY", "secret-key")
    # Use a fresh timestamp so we fail at signature comparison, not skew.
    timestamp = str(int(time.time()))
    assert evw.verify_mailgun_signature(timestamp, "tok", "deadbeef") is False


def test_mailgun_replay_rejected_when_timestamp_stale(monkeypatch):
    """WS-082: a captured-and-replayed Mailgun payload (>5min old) is dropped."""
    monkeypatch.setenv("WEBHOOKS_REQUIRE_SIGNING", "true")
    monkeypatch.setenv("MAILGUN_WEBHOOK_SIGNING_KEY", "secret-key")
    stale_ts = str(int(time.time()) - 3600)  # 1 hour ago
    token = "abc123"
    sig = hmac.new(
        b"secret-key",
        (stale_ts + token).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    # Signature itself is mathematically valid; only the timestamp check fails.
    assert evw.verify_mailgun_signature(stale_ts, token, sig) is False


def test_sendgrid_replay_rejected_when_timestamp_stale(monkeypatch):
    """WS-082: SendGrid replays of stale timestamps must be rejected even
    when the ECDSA signature is mathematically valid."""
    monkeypatch.setenv("WEBHOOKS_REQUIRE_SIGNING", "true")
    # Configure a public key so the function proceeds past the dev-mode
    # short-circuit. The ECDSA verification path isn't reached because the
    # timestamp gate fails first.
    monkeypatch.setenv("SENDGRID_WEBHOOK_PUBLIC_KEY", "AAAA")  # any non-empty
    stale_ts = str(int(time.time()) - 3600)
    assert evw.verify_sendgrid_signature(b"payload", stale_ts, "sigb64") is False


def test_postmark_valid_basic_auth_accepted(monkeypatch):
    monkeypatch.setenv("WEBHOOKS_REQUIRE_SIGNING", "true")
    monkeypatch.setenv("POSTMARK_WEBHOOK_BASIC_AUTH", "alice:hunter2")
    encoded = base64.b64encode(b"alice:hunter2").decode("ascii")
    assert evw.verify_postmark_basic_auth(f"Basic {encoded}") is True


def test_postmark_wrong_credentials_rejected(monkeypatch):
    monkeypatch.setenv("WEBHOOKS_REQUIRE_SIGNING", "true")
    monkeypatch.setenv("POSTMARK_WEBHOOK_BASIC_AUTH", "alice:hunter2")
    encoded = base64.b64encode(b"alice:wrong").decode("ascii")
    assert evw.verify_postmark_basic_auth(f"Basic {encoded}") is False


def test_ses_topic_allowlist_match(monkeypatch):
    monkeypatch.setenv("WEBHOOKS_REQUIRE_SIGNING", "true")
    monkeypatch.setenv(
        "SES_SNS_TOPIC_ARN_ALLOWLIST",
        "arn:aws:sns:us-east-1:111:ours, arn:aws:sns:us-east-1:111:also-ours",
    )
    assert evw.is_allowed_sns_topic("arn:aws:sns:us-east-1:111:ours") is True
    assert evw.is_allowed_sns_topic("arn:aws:sns:us-east-1:111:rogue") is False


# ----- SubscribeURL SSRF guard --------------------------------------------


def test_subscribe_url_rejects_attacker_host():
    assert evw.is_safe_sns_subscribe_url("https://evil.example.com/confirm") is False
    assert evw.is_safe_sns_subscribe_url("http://sns.us-east-1.amazonaws.com/c") is False
    assert evw.is_safe_sns_subscribe_url("") is False


def test_subscribe_url_accepts_aws_host():
    assert (
        evw.is_safe_sns_subscribe_url("https://sns.us-east-1.amazonaws.com/?Action=ConfirmSubscription")
        is True
    )


# ----- SNS message-signature verification (WS-082) -------------------------


def _build_signed_sns_notification(signing_key, signing_cert_pem) -> dict:
    """Build a fully-signed SNS Notification payload using the supplied
    RSA private key. Returns the payload dict ready for verify_sns_message_signature."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    payload = {
        "Type": "Notification",
        "MessageId": "msg-1",
        "Subject": "test",
        "Message": '{"eventType":"Bounce"}',
        "Timestamp": "2025-01-01T00:00:00Z",
        "TopicArn": "arn:aws:sns:us-east-1:111:ours",
        "SignatureVersion": "1",
        "SigningCertURL": "https://sns.us-east-1.amazonaws.com/cert.pem",
    }
    canonical = evw._canonical_sns_string(payload)
    signature = signing_key.sign(canonical, padding.PKCS1v15(), hashes.SHA1())
    payload["Signature"] = base64.b64encode(signature).decode("ascii")
    return payload


def _make_rsa_cert():
    """Build an in-memory RSA key + self-signed X.509 cert for testing."""
    from datetime import datetime, timedelta, timezone
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return key, cert


def test_sns_signature_rejects_when_signing_cert_url_is_attacker_host(monkeypatch):
    """WS-082: even with a TopicArn that's in the allowlist, the SigningCertURL
    pointing at a non-AWS host must be rejected (blocks SSRF + cert-of-choice)."""
    monkeypatch.setenv(
        "SES_SNS_TOPIC_ARN_ALLOWLIST", "arn:aws:sns:us-east-1:111:ours"
    )
    payload = {
        "Type": "Notification",
        "TopicArn": "arn:aws:sns:us-east-1:111:ours",
        "MessageId": "x",
        "Message": "{}",
        "Timestamp": "2025-01-01T00:00:00Z",
        "SignatureVersion": "1",
        "Signature": "AAAA",
        "SigningCertURL": "https://evil.example.com/cert.pem",
    }
    assert evw.verify_sns_message_signature(payload) is False


def test_sns_signature_verifies_valid_payload(monkeypatch):
    """Happy path: a payload signed with the cert we serve verifies."""
    monkeypatch.setenv(
        "SES_SNS_TOPIC_ARN_ALLOWLIST", "arn:aws:sns:us-east-1:111:ours"
    )
    key, cert = _make_rsa_cert()
    payload = _build_signed_sns_notification(key, cert)

    # Pre-populate the verifier's cert cache so we don't hit the network.
    evw._sns_cert_cache[payload["SigningCertURL"]] = cert
    try:
        assert evw.verify_sns_message_signature(payload) is True
    finally:
        evw._sns_cert_cache.pop(payload["SigningCertURL"], None)


def test_sns_signature_rejects_tampered_payload(monkeypatch):
    """Mutating any signed field after signing must invalidate the sig."""
    monkeypatch.setenv(
        "SES_SNS_TOPIC_ARN_ALLOWLIST", "arn:aws:sns:us-east-1:111:ours"
    )
    key, cert = _make_rsa_cert()
    payload = _build_signed_sns_notification(key, cert)
    payload["Message"] = '{"eventType":"Complaint"}'  # tamper

    evw._sns_cert_cache[payload["SigningCertURL"]] = cert
    try:
        assert evw.verify_sns_message_signature(payload) is False
    finally:
        evw._sns_cert_cache.pop(payload["SigningCertURL"], None)


def test_sns_signature_dev_mode_passes_through_when_allowlist_empty(monkeypatch):
    """When no SES allowlist is configured (dev), the verifier short-circuits to True
    so that local testing doesn't require cert fetches. Mirrors is_allowed_sns_topic."""
    monkeypatch.setenv("WEBHOOKS_REQUIRE_SIGNING", "false")
    monkeypatch.setenv("SES_SNS_TOPIC_ARN_ALLOWLIST", "")
    payload = {"Type": "Notification"}
    assert evw.verify_sns_message_signature(payload) is True
