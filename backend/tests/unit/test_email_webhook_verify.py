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
    timestamp = "1700000000"
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
    assert evw.verify_mailgun_signature("1700000000", "tok", "deadbeef") is False


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
